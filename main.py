from jmspider import JMSpider

# TODO 修改check逻辑，或者check一个漫画，看是不是一路走到底,下载后直接中断

if __name__ == '__main__':
    jms = JMSpider()
    jms.check_search()
    jms.download_comic_3()