import asyncio
import logging
import sys
import os

# Add the 'src' directory to the Python path to allow direct imports of 'cqt'
# This is useful when running main.py from the project root.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

from cqt.core.event import Event, EventBus, MarketEvent
from cqt.utils.logging import setup_logging

# It's good practice for modules to get their own logger.
# The main entry point can get the root logger of our application.
logger = logging.getLogger('cqt.main')


async def event_producer(event_bus: EventBus):
    """
    A simple coroutine that produces events and puts them into the event bus.
    """
    for i in range(5):
        await asyncio.sleep(1) # Simulate some work or a delay
        event = MarketEvent(symbol="BTC/USDT", data={'price': 50000 + i * 100})
        logger.info(f"Producer: Putting event on the bus -> {event.type} for {event.symbol}")
        await event_bus.put(event)

    # Signal that the producer is done
    await event_bus.put(None)


async def event_consumer(event_bus: EventBus):
    """
    A simple coroutine that consumes events from the event bus.
    """
    logger.info("Consumer: Waiting for events...")
    while True:
        event = await event_bus.get()
        if event is None: # A signal to stop consuming
            logger.info("Consumer: Received stop signal. Exiting.")
            event_bus.task_done()
            break

        logger.info(f"Consumer: Got event from the bus <- {event.type} for {event.symbol} with data {event.data}")
        # In a real engine, this would dispatch the event to handlers
        event_bus.task_done()


async def main():
    """
    Main entry point for the application demonstration.
    """
    # 1. Setup logging
    # This configures the 'cqt' logger, which our module loggers will inherit from.
    setup_logging(level=logging.INFO)

    logger.info("--- Framework Core System Demo ---")

    # 2. Initialize the Event Bus
    event_bus = EventBus()
    logger.info("Event Bus initialized.")

    # 3. Create producer and consumer tasks
    producer_task = asyncio.create_task(event_producer(event_bus))
    consumer_task = asyncio.create_task(event_consumer(event_bus))

    # 4. Wait for the producer to finish, and then for the consumer to process all items
    await producer_task
    logger.info("Producer has finished its work.")

    await event_bus.join() # Wait until the queue is fully processed
    logger.info("Event bus queue has been fully processed.")

    # Consumer task will exit on its own after receiving None
    # We can await it to ensure it has cleaned up if needed.
    await consumer_task

    logger.info("--- Demo Finished ---")


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application interrupted by user.")
    except Exception as e:
        logger.error(f"An unhandled error occurred: {e}", exc_info=True)
