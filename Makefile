.PHONY: up down test logs demo

up:
	docker compose up -d

down:
	docker compose down

test:
	pytest

logs:
	docker compose logs -f

demo:
	docker compose up -d --build
