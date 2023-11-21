# backend


## Description
The application builds api for the rider expert project
## 1. Setup

### Using Docker

If you don't have docker. You can follow the instructions [here](https://docs.docker.com/engine/install/) and start the application

After installing docker desktop ensure the app is opened then follow the steps below

To run the application run the following command in terminal from this project root directory

```sh
docker-compose up
```

To run the django commands run the command below to access docker interactive

```sh
docker exec -it backend-web-1 bash 
```

Then you'd be  able to run commands like python manage.py ...

Application should be running on http:127.0.0.1:8000

### Dropping database

To drop the current database to run the migrations again.

1. ensure Docker is running
2. Start up the database service alone using `docker-compose up db`
3. Open another terminal and run `docker-compose exec db bash`
4. In that terminal enter `psql -U riderexpert`
5. Run the following 
```
drop schema public cascade; 
create schema public;
```
6. exit the database by entering `\q`
7. Close the docker-compose `docker-compose down`
8. You can now spin up the entire container using `docker-compose up`


### Rolling back Migrations
1. enter into the web bash `docker exec -it backend-web-1 bash ` or `docker-compose exec web bash`. N.B ensure your docker is running
2. a. the run `python manage.py migrate <app_name> zero` to roll back all migrations in that app
2. b. Run `python manage.py migrate <app_name> <migration_id>` to roll back to all migrations after the migration_id
