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
parser.add_argument('--config', type=str, help='Path to configuration file', default=None)

args = parser.parse_args()

if(args.config):
    print('Using config file: ' + args.config)
    config_file = open(args.config, 'r')
    

report = ''

url = args.url

if (validators.url(url)):
    result_html = requests.get(url).text
    parsed_html = BeautifulSoup(result_html, 'html.parser')

    forms           = parsed_html.find_all('form')
    comments        = parsed_html.find_all(string=lambda text: isinstance(text, Comment))
    password_inputs = parsed_html.find_all('input', {'name': 'password'})
    
    for form in forms:
        if((form.get('action').find('https') < 0 and (urlparse(url).scheme != 'https'))):
            report += '[!] Form with non-HTTPS action found: Insecure form action ' + form.get('action') + ' found in document \n{}\n'.format(form)

    for comment in comments:
        if(comment.find('key: ') > -1):
            report += '[!] Sensitive information found in HTML comments: ' + comment + '\n'

    for password_input in password_inputs:
        if(password_input.get('type') != 'password'):
            report += '[!] Insecure password input field found: ' + str(password_input) + '\n'
    
else:
    print('Invalid URL. Please provide a valid URL scheme.')


if(report == ''):
    print('No issues found.')
else:  
    print("Vulnerability Report is as follows:\n") 
    print('-----------------------------------\n')
    print(report)