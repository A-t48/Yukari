import codecs
from ConfigParser import SafeConfigParser

parser = SafeConfigParser()
with codecs.open('settings.cfg', 'r', encoding='utf-8') as f:
    parser.readfp(f)

cfg = {}
for section in parser.sections():
    cfg[section] = dict(parser.items(section))

