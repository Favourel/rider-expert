import logging
import math
from decimal import Decimal

from django.db.models import Avg

from accounts.models import Rider
from map_clients.map_clients import MapClientsManager, get_distance
from map_clients.supabase_query import SupabaseTransactions
from accounts.utils import (
    DistanceCalculator,
    generate_otp,
    send_customer_notification,
    send_riders_notification,
    str_to_bool,
)
from multi_orders.models import SupportTicket, OrderRiderAssignment
from orders.models import Order

# Initialize external dependencies
map_clients_manager = MapClientsManager()
supabase = SupabaseTransactions()

# Logger configuration
logger = logging.getLogger(__name__)

DEFAULT_RIDER_CAPACITY = Decimal('50.00')
DEFAULT_ORDER_STATUS = 'Pending'
DEFAULT_PRIORITY = 'medium'


class MultiRiderOrderErrorHandlingMixin:
    """
    Centralized error handling and logging for multi-rider order processes.
    Includes methods for resolving common errors and fallback mechanisms.
    """

    def assign_bulk_orders(self, order, destinations, total_weight, is_fragile):
        """
        Handles assignment of bulk orders to riders.

        Args:
            order (Order): The main order to split.
            destinations (list): List of destination coordinates.
            total_weight (Decimal): Total weight of the shipment.
            is_fragile (bool): Whether the items are fragile.

        Returns:
            dict: Status of the bulk assignment and assigned riders.
        """
        try:
            avg_capacity = Rider.objects.aggregate(avg=Avg('max_capacity'))['avg'] or Decimal('50.00')
            shipment_size = min(avg_capacity, total_weight)

            # Split the weight and assign riders
            shipments = []
            remaining_weight = total_weight
            assigned_riders = []

            for destination in destinations:
                if remaining_weight <= 0:
                    break

                # fields = ["rider_email", "current_lat", "current_long"]
                # riders_location_data = supabase.get_supabase_riders(fields=fields)
                #
                # # Filter riders who can handle the shipment
                # suitable_riders = Rider.objects.filter(
                #     user__email__in=[rider['email'] for rider in riders_location_data],
                #     min_capacity__lte=total_weight,
                #     max_capacity__gte=total_weight,
                #     fragile_item_allowed=is_fragile
                # )

                rider_candidates = Rider.objects.filter(
                    max_capacity__gte=shipment_size,
                    fragile_item_allowed=is_fragile
                ).annotate(distance=DistanceCalculator(destination))

                if not rider_candidates.exists():
                    self.handle_order_assignment_errors(order, 'no_riders_available')
                    continue

                # Assign the nearest rider
                rider = rider_candidates.order_by('distance').first()
                assignable_weight = min(rider.max_capacity, remaining_weight)

                assignment = OrderRiderAssignment.objects.create(
                    order=order,
                    rider=rider,
                    status='Assigned',
                    assigned_weight=assignable_weight,
                    destination=destination,
                )

                remaining_weight -= assignable_weight
                assigned_riders.append(rider)
                shipments.append(assignment)

                # Notify rider
                send_riders_notification.delay(
                    riders=[{"email": rider.user.email}],
                    price=order.price,
                    message=f"You have been assigned a bulk shipment to {destination}.",
                    order_id=order.pk,
                )

            return {
                "status": "success",
                "shipments": [s.id for s in shipments],
                "remaining_weight": remaining_weight,
            }
        except Exception as e:
            logger.error(f"Error in bulk order assignment: {str(e)}")
            self.handle_order_assignment_errors(order, 'bulk_assignment_failure')
            return {"status": "error", "message": str(e)}

    def handle_order_assignment_errors(self, order, error_type):
        """
        Handles errors during order assignment and maps them to appropriate resolution strategies.

        Args:
            order (Order): The order experiencing issues.
            error_type (str): Specific type of error encountered.
        """
        error_mapping = {
            'insufficient_capacity': {
                'message': 'No riders can fulfill the entire shipment.',
                'severity': 'high',
                'action': self.handle_insufficient_capacity
            },
            'no_riders_available': {
                'message': 'No riders found matching shipment criteria.',
                'severity': 'medium',
                'action': self.resolve_no_riders_available
            },
            'partial_assignment_failure': {
                'message': 'Unable to complete partial rider assignments.',
                'severity': 'critical',
                'action': self.resolve_partial_assignment_failure
            },
        }

        error_config = error_mapping.get(
            error_type,
            {
                'message': 'Unhandled order assignment error.',
                'severity': 'low',
                'action': self.default_error_resolution,
            }
        )

        logger.error(
            f"Order Assignment Error: {error_config['message']}",
            extra={
                'order_id': order.id,
                'error_type': error_type,
                'severity': error_config['severity']
            }
        )

        # Execute the specific error handling action
        error_config['action'](order)

        # Always log and create a support ticket for tracking
        self.create_internal_support_ticket(
            ticket_type=f"{error_type}_resolution_needed",
            order=order
        )

    def handle_insufficient_capacity(self, order):
        """
        Handles cases where no riders can fulfill the entire shipment.
        Splits the order into smaller shipments and notifies the customer.

        Args:
            order (Order): The order experiencing capacity issues.
        """
        self.split_order_into_smaller_shipments(order)
        send_customer_notification.delay(
            customer=order.customer.user.email,
            message="Shipment requires special handling. Our team will contact you."
        )

    def split_order_into_smaller_shipments(self, order):
        """
        Divides a large order into smaller, manageable shipments using batch operations.

        Args:
            order (Order): The order to be split.

        Returns:
            List of new Order objects or None in case of failure.
        """
        try:
            avg_rider_capacity = Rider.objects.aggregate(avg_max_capacity=Avg('max_capacity'))[
                                     'avg_max_capacity'] or DEFAULT_RIDER_CAPACITY

            weight = order.weight
            num_shipments = math.ceil(weight / avg_rider_capacity)

            new_orders = []
            remaining_weight = weight

            for _ in range(num_shipments):
                current_shipment_weight = min(avg_rider_capacity, remaining_weight)
                new_orders.append(Order(
                    customer=order.customer,
                    pickup_lat=order.pickup_lat,
                    pickup_long=order.pickup_long,
                    recipient_lat=order.recipient_lat,
                    recipient_long=order.recipient_long,
                    weight=current_shipment_weight,
                    fragile=order.fragile,
                    status=DEFAULT_ORDER_STATUS,
                    parent_order=order,
                ))
                remaining_weight -= current_shipment_weight

            Order.objects.bulk_create(new_orders)

            order.status = 'Split'
            order.save()

            logger.info(f"Order {order.id} split into {num_shipments} shipments",
                        extra={'order_id': order.id, 'num_shipments': num_shipments}
            )
            return new_orders

        except Exception as e:
            logger.error(
                f"Error splitting order {order.id}",
                extra={'order_id': order.id, 'error_type': type(e).__name__, 'error_details': str(e)}
            )
            return None

    def resolve_no_riders_available(self, order):
        """Notifies the customer and updates the order when no riders are available."""
        send_customer_notification.delay(
            customer=order.customer.user.email,
            message="Delivery currently unavailable. Our team will contact you shortly.",
        )
        order.status = 'Pending_External_Resolution'
        order.save()

    def resolve_partial_assignment_failure(self, order):
        """Handles partial assignment failures and notifies the customer."""
        OrderRiderAssignment.objects.filter(order=order).delete()
        order.status = 'Assignment_Failed'
        order.save()
        send_customer_notification.delay(
            customer=order.customer.user.email,
            message="We're experiencing issues with your delivery. Our team will contact you."
        )

        self.create_internal_support_ticket(
            ticket_type='multi_rider_assignment_failure',
            order=order
        )

    def create_internal_support_ticket(self, ticket_type, order):
        """
        Creates a support ticket for tracking unresolved or complex issues.

        Args:
            ticket_type (str): Type of the support ticket.
            order (Order): Order associated with the ticket.
        """
        try:
            priority_mapping = {
                'multi_rider_assignment_failure': 'high',
                'capacity_allocation_issue': 'critical',
                'order_splitting_error': 'high',
            }

            support_ticket = SupportTicket.objects.create(
                ticket_type=ticket_type,
                priority=priority_mapping.get(ticket_type, 'medium'),
                order=order,
                description=(
                    f"Multi-Rider Order Assignment Issue\n\n"
                    f"Order ID: {order.id}\n"
                    f"Total Weight: {order.weight}\n"
                    f"Customer: {order.customer.user.email}\n"
                    f"Status: {order.status}\n\n"
                    f"Action Required: Immediate intervention."
                ),
                assigned_team='logistics_support',
            )

            # send_team_notification.delay(
            #     team='logistics_support',
            #     message=f"High Priority Ticket Created: Order {order.id} requires attention",
            #     ticket_id=support_ticket.id,
            # )

            logger.info(
                f"Support ticket created for Order {order.id}",
                extra={
                    'order_id': order.id,
                    'ticket_id': support_ticket.id,
                    'ticket_type': ticket_type
                }
            )

        except Exception as e:
            logger.error(
                f"Failed to create support ticket for Order {order.id}",
                extra={
                    'order_id': order.id,
                    'error_type': type(e).__name__,
                    'error_details': str(e)
                }
            )

    def default_error_resolution(self, order):
        """Fallback method for unhandled errors."""
        order.status = 'Unresolved'
        order.save()
        logger.warning(
            f"Default error resolution applied to Order {order.id}",
            extra={
                'order_id': order.id,
                'current_status': order.status
            }
        )
