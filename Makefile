.PHONY: up down migrate logs lint type test ci clean observe

COMPOSE := docker compose

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down --remove-orphans

observe:
	$(COMPOSE) -f docker-compose.yml -f docker-compose.observe.yml --profile observe up -d

migrate:
	$(COMPOSE) run --rm migrate

logs:
	$(COMPOSE) logs -f --tail=200

lint:
	ruff check .
	ruff format --check .

type:
	mypy api/src migrate/alembic

test:
	pytest

ci: lint type test

clean:
	$(COMPOSE) down -v --remove-orphans
