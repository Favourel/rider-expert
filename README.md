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