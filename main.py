from jmspider import JMSpider
from database.crud import query_comic

if __name__ == '__main__':
    jms = JMSpider()
    jms.check_search()
    jms.download_comic_2()