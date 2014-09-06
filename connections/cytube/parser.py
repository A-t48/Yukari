from HTMLParser import HTMLParser
import htmlentitydefs

class HTMLStripper(HTMLParser):
    def __init__(self):
        HTMLParser.__init__(self)
        self.result = []
    def handle_data(self, d):
        self.result.append(d)
    def  handle_charref(self, number):
        if number[0] in (u'x', u'X'):
            codepoint = int(number[1:], 16)
        else:
            codepoint = int(number)
        self.result.append(unichr(codepoint))
    def  handle_entityref(self, name):
        codepoint = htmlentitydefs.name2codepoint[name]
        self.result.append(unichr(codepoint))
    def get_data(self):
        return ''.join(self.result)

def stripTags(html):
    s = HTMLStripper()
    s.feed(html)
    return s.get_data()

def unescapeEntity(html, p=HTMLParser()):
    if not html:
        return ''
    return p.unescape(html)

