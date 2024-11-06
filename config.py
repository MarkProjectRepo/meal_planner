# API Configuration
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.2"
OLLAMA_TIMEOUT = 30.0

# Logging Configuration
LOG_FILE = "meal_planner.log"
LOG_MAX_BYTES = 10000
LOG_BACKUP_COUNT = 1
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
LOG_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

# File Export Configuration
EXPORT_DATE_FORMAT = "%Y%m%d_%H%M%S"
EXPORT_FILENAME_PREFIX = "shopping_list" 