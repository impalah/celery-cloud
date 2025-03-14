#!/usr/bin/env python3
from celery_cloud.celery_worker import start_worker


def main():
    print("Starting worker")
    start_worker()


if __name__ == "__main__":
    main()
