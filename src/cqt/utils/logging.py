import logging
import sys
from typing import Optional

def setup_logging(level: int = logging.INFO, log_to_file: Optional[str] = None):
    """
    Configures the root logger for the application.

    :param level: The minimum logging level to output (e.g., logging.INFO, logging.DEBUG).
    :param log_to_file: Optional. If a file path is provided, logs will also be written to this file.
    """
    # Use a specific name for the framework's logger to avoid interfering with other libraries' root loggers
    logger = logging.getLogger('cqt')
    logger.setLevel(level)

    # Prevent logs from being propagated to the root logger if it has handlers
    logger.propagate = False

    # Create a formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Clear existing handlers to avoid duplicate logs if this function is called multiple times
    if logger.hasHandlers():
        logger.handlers.clear()

    # Create a console handler (StreamHandler) to log to stdout
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Create a file handler if a path is provided
    if log_to_file:
        try:
            file_handler = logging.FileHandler(log_to_file, mode='a') # 'a' for append
            file_handler.setLevel(level)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
            logger.info(f"Logging configured to write to file: {log_to_file}")
        except Exception as e:
            logger.error(f"Failed to configure file logging to {log_to_file}: {e}")

    logger.info(f"Logger 'cqt' configured with level {logging.getLevelName(level)}.")

# Example of how other modules should get the logger:
# import logging
# logger = logging.getLogger(__name__) # Good practice: use __name__ for module-specific loggers
# This works because getLogger('cqt.core.engine') will inherit from the 'cqt' logger we configured.

if __name__ == '__main__':
    print("--- Testing Logging Setup ---")

    print("\n1. Testing INFO level logging to console...")
    setup_logging(level=logging.INFO)
    main_logger = logging.getLogger('cqt.main_test') # Get a child logger
    main_logger.debug("This is a debug message. Should NOT be visible.")
    main_logger.info("This is an info message. Should be visible.")
    main_logger.warning("This is a warning message. Should be visible.")
    main_logger.error("This is an error message. Should be visible.")

    print("\n2. Testing DEBUG level logging to console...")
    setup_logging(level=logging.DEBUG)
    main_logger.debug("This is a debug message. Should NOW be visible.")

    print("\n3. Testing logging to a file...")
    test_log_file = "test_log.log"
    import os
    if os.path.exists(test_log_file):
        os.remove(test_log_file)

    setup_logging(level=logging.INFO, log_to_file=test_log_file)
    file_test_logger = logging.getLogger('cqt.file_test')
    file_test_logger.info("This message should be in the console AND the test_log.log file.")
    file_test_logger.warning("This warning should also be in both.")

    if os.path.exists(test_log_file):
        print(f"\nContents of {test_log_file}:")
        with open(test_log_file, 'r') as f:
            print(f.read())
        os.remove(test_log_file)
    else:
        print(f"Error: {test_log_file} was not created.")

    print("\n--- Logging Setup Test End ---")
