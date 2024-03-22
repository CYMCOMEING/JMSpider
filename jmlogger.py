import os
import logging


logger = logging.getLogger('jm_spider')
logger.setLevel(logging.INFO)

formatter = logging.Formatter(
    '[%(asctime)s]-[%(name)s]-[%(levelname)s]: %(message)s')

work_dir = os.path.abspath('.')
log_dir = os.path.join(work_dir, 'data')
logfile = os.path.join(log_dir, 'jm_spider.log')
os.makedirs(log_dir, exist_ok=True)
# if not os.path.exists(log_dir):
#     os.mkdir(log_dir)

fh = logging.FileHandler(logfile, encoding='utf-8')
fh.setLevel(logging.INFO)
fh.setFormatter(formatter)

logger.addHandler(fh)
