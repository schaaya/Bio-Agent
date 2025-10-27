#!/bin/bash
 
today_date=$(date +"%Y-%m-%d")
 
#docker stop the running containerr and remove
docker stop bi-bot && docker rm bi-bot
 
#docker remove existing image
docker rmi bi-bot:"$today_date"
 
#Build docker image
docker build -t bi-bot:"$today_date" .
 
#docker create container
docker run -it -d --name bi-bot -p 8400:8400 bi-bot:"$today_date"