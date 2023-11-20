from django.shortcuts import render
from .tokens import create_jwt_pair_for_user

# display success login info with the created token data
# tokens = create_jwt_pair_for_user(user)
# response = {"message": "Login Successful", "tokens": tokens}
