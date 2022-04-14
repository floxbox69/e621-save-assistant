import json

def read_json_file(filename, default_value):
    try:
        with open(filename, 'r') as file:
            return json.load(file)
    except FileNotFoundError:
        return default_value

def save_json_file(filename, contents):
    with open(filename, 'w') as file:
        json.dump(contents, file)

def read_file_lines(filename, default_value):
    try:
        with open(filename, 'r') as file:
            return [ line.rstrip() for line in file ]
    except FileNotFoundError:
        return default_value

def save_file_lines(filename, contents):
    with open(filename, 'w') as file:
        file.write('\n'.join(contents))