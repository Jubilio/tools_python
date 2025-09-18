#! /usr/bin/env python3

import argparse
import validators
import requests
import yaml
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from bs4 import Comment


parser = argparse.ArgumentParser(description="The Achilles HTML Vulnerabitility Analyzer Version 1.0")

parser.add_argument('-v', '--version', action='version', version='%(prog)s 1.0')
parser.add_argument('url', type=str, help='The target URL of HTML to analyze')
parser.add_argument('--config', help='Path to configuration file')
parser.add_argument('-o', '--output', help='Report file output path')

args = parser.parse_args()

config = {'forms': True, 'comments': True, 'passwords': True}
if(args.config):
    print('Using config file: ' + args.config)
    config_file = open(args.config, 'r')
    config_from_file = yaml.load(config_file, Loader=yaml.FullLoader)
    if(config_from_file):
        config = { **config, **config_from_file }
    

report = ''

url = args.url

if (validators.url(url)):
    result_html = requests.get(url).text
    parsed_html = BeautifulSoup(result_html, 'html.parser')

    forms           = parsed_html.find_all('form')
    comments        = parsed_html.find_all(string=lambda text: isinstance(text, Comment))
    password_inputs = parsed_html.find_all('input', {'name': 'password'})

    if(config['forms']):
        for form in forms:
            if((form.get('action').find('https') < 0 and (urlparse(url).scheme != 'https'))):
                report += '[!] Form with non-HTTPS action found: Insecure form action ' + form.get('action') + ' found in document \n{}\n'.format(form)

    if(config['comments']):
        for comment in comments:
            if(comment.find('key: ') > -1):
                report += '[!] Sensitive information found in HTML comments: ' + comment + '\n'

    if(config['passwords']):
        for password_input in password_inputs:
            if(password_input.get('type') != 'password'):
                report += '[!] Insecure password input field found: ' + str(password_input) + '\n'
    
else:
    print('Invalid URL. Please provide a valid URL scheme.')


if(report == ''):
    print('No issues found. Your HTML documents is secure!\n')
else:  
    header  = '-----------------------------------\n'
    header += "Vulnerability Report is as follows:\n" 
    header += '-----------------------------------\n\n'
    
    report = header + report

print(report)

if(args.output):
    f = open(args.output, 'w')
    f.write(report)
    f.close
    print('Report saved at: ' + args.output)