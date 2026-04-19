.PHONY: build run stop clean up down logs logs-api logs-mcp restart init

# Variables
IMAGE_NAME = costaff-agent-service
CONTAINER_NAME = costaff-agent-instance

# Docker native commands
build:
	docker build -t $(IMAGE_NAME) .

run:
	docker run -d --name $(CONTAINER_NAME) --env-file .env -p 8080:8080 $(IMAGE_NAME)

stop:
	docker stop $(CONTAINER_NAME) || true
	docker rm $(CONTAINER_NAME) || true

clean:
	docker rmi $(IMAGE_NAME) || true

# Docker Compose commands
up:
	mkdir -p data
	docker-compose -f docker-compose.local.yaml up -d --build

down:
	docker-compose -f docker-compose.local.yaml down

logs:
	docker-compose -f docker-compose.local.yaml logs -f

logs-agent:
	docker-compose -f docker-compose.local.yaml logs -f costaff-agent-costaff

logs-reminder:
	docker-compose -f docker-compose.local.yaml logs -f costaff-mcp-reminder

logs-privai:
	docker-compose -f docker-compose.local.yaml logs -f costaff-mcp-privai

restart:
	docker-compose -f docker-compose.local.yaml up -d --build

# Initialize environment
init:
	@if [ ! -f .env ]; then \
		cp .env.template .env; \
		echo ".env file created from template. Please edit it with your credentials."; \
	else \
		echo ".env file already exists."; \
	fi
	mkdir -p data