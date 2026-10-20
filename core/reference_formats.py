"""Extract literal configuration references without executing configuration code."""
import configparser
import json
import ntpath
import re
import tomllib
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

STRUCTURED_EXTENSIONS = frozenset({'.json', '.toml', '.ini', '.cfg', '.conf',
                                  '.url', '.xml', '.css', '.html', '.htm'})


def structured_references(path, text):
    suffix = path.suffix.lower()
    values = []
    errors = []

    def visit(value, location):
        if isinstance(value, dict):
            for key, item in value.items():
                visit(item, f'{location}.{key}')
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f'{location}[{index}]')
        elif isinstance(value, str):
            values.append((location, value))

    try:
        if suffix == '.json':
            visit(json.loads(text), '$')
        elif suffix == '.toml':
            visit(tomllib.loads(text), '$')
        elif suffix in {'.ini', '.cfg', '.conf', '.url'}:
            parser = configparser.ConfigParser(interpolation=None, strict=True)
            parser.read_string(text)
            for section in parser.sections():
                for key, value in parser.items(section):
                    values.append((f'{section}.{key}', value))
        elif suffix == '.xml':
            if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
                raise ValueError('XML entity/doctype input excluded')
            for node in ET.fromstring(text).iter():
                values.extend((f'{node.tag}@{key}', value) for key, value in node.attrib.items())
                if node.text and node.text.strip():
                    values.append((node.tag, node.text.strip()))
        elif suffix == '.css':
            values.extend(('url', m.group(1).strip(' \"\'')) for m in re.finditer(r'url\(([^)]+)\)', text))
        elif suffix in {'.html', '.htm'}:
            class References(HTMLParser):
                def handle_starttag(self, tag, attrs):
                    for key, value in attrs:
                        if value and key in {'src', 'href', 'poster', 'data'}:
                            values.append((f'{tag}@{key}', value))
                        elif value and key == 'srcset':
                            errors.append('HTML srcset requires separate candidate parsing')
                    if tag == 'base':
                        errors.append('HTML base changes resolution; relative references unresolved')
            parser = References(convert_charrefs=True)
            parser.feed(text)
            parser.close()
    except (ValueError, configparser.Error, ET.ParseError) as exc:
        errors.append(str(exc))
    result = []
    for location, value in values:
        value = value.strip().strip('"')
        # IconResource may include a resource index. Never expand scripts or variables.
        if location.lower().endswith('iconresource'):
            value = re.sub(r',-?\d+$', '', value)
        dynamic = any(token in value for token in ('#', '%', '$', '*', '?'))
        if suffix in {'.html', '.htm'} and any('HTML base' in error for error in errors):
            dynamic = True
        if dynamic:
            result.append({'field': location, 'raw': value, 'state': 'UNRESOLVED_DYNAMIC'})
        elif value and not re.match(r'^[a-z][a-z0-9+.-]*:', value, re.I) and not value.startswith('//'):
            resolved = ntpath.normpath(ntpath.join(str(path.parent), value))
            result.append({'field': location, 'raw': value, 'resolved': resolved,
                           'state': 'LITERAL_REFERENCE_CANDIDATE'})
        elif re.match(r'^[a-z]:[\\/]', value, re.I):
            result.append({'field':location, 'raw':value, 'resolved':ntpath.normpath(value),
                           'state':'LITERAL_REFERENCE_CANDIDATE'})
    return result, errors
