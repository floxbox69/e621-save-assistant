import PySimpleGUI as sg
import os
import io
import requests
import shutil
from enum import Enum
from PIL import Image

import util

class ImageFetchResponse(Enum):
    REACHED_END = 1
    FETCH_ERROR = 2

class Curator:
    # Version number
    VERSION = '1.0.0'

    # User settings
    SETTINGS_FILENAME = './settings.json'

    # A list of tag sets
    TAGS_FILENAME = './tags.txt'

    # A list of blacklisted tags
    BLACKLIST_FILENAME = './blacklist.txt'

    # The latest post that was looked at for each tag set. If this post is reached, the autosaver got through all
    # new images of that tag set
    LATEST_POSTS_FILENAME = './latest_posts.json' 

    # The tag set and image that was last looked at. Continue from here
    LAST_POST_FILENAME = './last_post.json'

    # "Checkpoints" for different tag sets. When encountering that tag set again, continue from the checkpoint
    TAG_SET_CHECKPOINTS_FILENAME = './checkpoints.json'

    # Folder for temporary image saving
    TEMP_IMAGE_FOLDER = './temp'

    # The minimum height of the image as displayed in the GUI. The width is scaled automatically,
    # respecting aspect ratio
    MIN_IMAGE_HEIGHT = 500

    # The maximum width of an image as a product of the window width.
    # If the scaled image is wider, it will be re-scaled with this width
    MAX_IMAGE_WIDTH = 0.6

    # The multiplier of the image height compared to the window height,
    # i.e. image_height = window_height * IMAGE_WINDOW_HEIGHT_MULTIPLIER (with minimum of MIN_IMAGE_HEIGHT)
    IMAGE_WINDOW_HEIGHT_MULTIPLIER = 0.65

    # Default window size (width, height)
    DEFAULT_WINDOW_SIZE = (1080, 800)

    # The layout of the UI
    layout = []
    small_text_elements = []

    # Image variables
    current_tag_set_num = 0
    current_image_num = 0
    full_image_filename = ''
    sample_image_filename = ''
    preview_image = None
    image_extension = ''
    image_height = MIN_IMAGE_HEIGHT
    image_artists = ''
    post_id = 0

    # User input
    settings = {}
    tag_sets = []
    blacklist = []

    # Variables to keep track of what posts have already been looked at
    latest_posts = {}
    last_post = {}
    tag_set_checkpoints = {}
    at_last_post = False
    continuing_from_last_post = False
    at_checkpoint = False
    continuing_from_checkpoint = False
    checkpoint_previous_post_id = 0

    def __init__(self):
        self.settings = self.read_settings()
        self.tag_sets = self.read_tag_sets()
        self.blacklist = self.read_blacklist()
        self.latest_posts = self.read_latest_posts()
        self.last_post = self.read_last_post()
        self.tag_set_checkpoints = self.read_tag_set_checkpoints()
        self.layout = self.create_layout()

        if not os.path.exists(self.TEMP_IMAGE_FOLDER):
            os.makedirs(self.TEMP_IMAGE_FOLDER)

    def read_settings(self):
        return util.read_json_file(self.SETTINGS_FILENAME, {})

    def apply_settings(self, window):
        if 'output_folder' in self.settings:
            window['folder'].update(self.settings['output_folder'])

    def save_settings(self):
        util.save_json_file(self.SETTINGS_FILENAME, self.settings)

    def read_tag_sets(self):
        return util.read_file_lines(self.TAGS_FILENAME, [])

    def save_tag_sets(self):
        util.save_file_lines(self.TAGS_FILENAME, self.tag_sets)

    def read_blacklist(self):
        return util.read_file_lines(self.BLACKLIST_FILENAME, [])

    def save_blacklist(self):
        util.save_file_lines(self.BLACKLIST_FILENAME, self.blacklist)

    def read_latest_posts(self):
        return util.read_json_file(self.LATEST_POSTS_FILENAME, {})

    def read_last_post(self):
        return util.read_json_file(self.LAST_POST_FILENAME, {})

    def read_tag_set_checkpoints(self):
        return util.read_json_file(self.TAG_SET_CHECKPOINTS_FILENAME, {})

    def create_layout(self):
        default_output_folder = self.settings['output_folder'] if 'output_folder' in self.settings else ''
        default_tag_sets = '\n'.join(self.tag_sets)
        default_blacklist = '\n'.join(self.blacklist)

        return [
            [sg.Text('Easily curate searches from e621', font=('', 18), key='title')],
            [
                sg.Text('Output folder', key='foldertext'),
                sg.In(default_output_folder, size=(35, 1), enable_events=True, key='folder'),
                sg.FolderBrowse()
            ],
            [sg.Button('Start', key='start')],
            [
                sg.Column([
                    [sg.Text(key='currenttagset')],
                    [sg.Text(key='artist')],
                    [sg.Column([[sg.Image(size=(300, self.MIN_IMAGE_HEIGHT), key='image')]], justification='center')],
                    [
                        sg.Column([[
                            sg.Button('Save Full', key='savefull', visible=False),
                            sg.Button('Save Sample', key='savesample', visible=False)
                        ]], justification='center')
                    ],
                    [
                        sg.Column([[
                            sg.Button('Skip', key='skip', visible=False),
                            sg.Button('Create Checkpoint', key='continuelater', visible=False),
                            sg.Button('Skip All', key='skiptagset', visible=False)
                        ]], justification='center')
                    ]
                ]),
                sg.VSeperator(),
                sg.Column([
                    [sg.Text('Tags (each line is a set that\'s searched; "order" not supported)', key='tagsetstext')],
                    [sg.Multiline(default_tag_sets, size=(40, 20), enable_events=True, key='tagsets',
                        horizontal_scroll=True)],
                    [sg.Text('Blacklist (one tag per line)', key='blacklisttext')],
                    [sg.Multiline(default_blacklist, size=(40, 10), enable_events=True, key='blacklist',
                        horizontal_scroll=True)]
                ])
            ]
        ]

    def run(self):
        window = sg.Window('e621 Save Assistant', self.layout, element_justification='c',
            size=self.DEFAULT_WINDOW_SIZE, resizable=True, finalize=True)
        window.bind('<Configure>', 'resizewindow')
        self.handle_event_loop(window)
        window.close()

    def handle_event_loop(self, window):
        prev_window_size = None
        while True:
            event, values = window.read()
            if event == sg.WIN_CLOSED:
                break

            if event == 'start':
                self.start(window)
            elif event == 'folder':
                self.settings['output_folder'] = values['folder']
                self.save_settings()
            elif event == 'savefull':
                self.save_image(is_full=True)
                self.load_new_image(window)
            elif event == 'savesample':
                self.save_image(is_full=False)
                self.load_new_image(window)
            elif event == 'skip':
                self.load_new_image(window)
            elif event == 'continuelater':
                result = sg.popup_yes_no('Are you sure you want to create a checkpoint and move onto the next tag set? Next time you get to this tag set, you will continue where you left off.')
                if result == 'Yes':
                    self.add_tag_set_checkpoint()
                    self.load_new_image(window, force_new_tag_set=True)
            elif event == 'skiptagset':
                result = sg.popup_yes_no('Are you sure you want to skip the rest of the images in the current tag set? Next time you get to this tag set, only new images will be shown.')
                if result == 'Yes':
                    self.clear_last_post()
                    self.load_new_image(window, force_new_tag_set=True)
            elif event == 'tagsets':
                self.tag_sets = values['tagsets'].split('\n')
                self.save_tag_sets()
            elif event == 'blacklist':
                self.blacklist = values['blacklist'].split('\n')
                self.save_blacklist()
            elif event == 'resizewindow':
                if prev_window_size is not None and window.size != prev_window_size:
                    self.resize_elements(window)
                prev_window_size = window.size

    def start(self, window):
        # Only start the process if the settings are reasonable
        if 'output_folder' not in self.settings or self.settings['output_folder'] == '':
            return
        if len(self.tag_sets) == 0:
            return

        # Start at last post, but only if tags of that post are still in the list
        if len(self.last_post) > 0 and self.last_post['tag_set'] in self.tag_sets:
            print(self.last_post)
            self.at_last_post = True
            self.continuing_from_last_post = True
            try:
                self.current_tag_set_num = self.tag_sets.index(self.last_post['tag_set'])
            except ValueError:
                self.current_tag_set_num = -1

        # Sanity checks passed. Load first image!
        self.load_new_image(window, just_started=True)

        # Toggle input fields / buttons
        window['start'].update(visible=False)
        window['savefull'].update(visible=True)
        window['savesample'].update(visible=True)
        window['skip'].update(visible=True)
        window['continuelater'].update(visible=True)
        window['skiptagset'].update(visible=True)
        window['tagsets'].update(disabled=True, background_color='gray')
        window['blacklist'].update(disabled=True, background_color='gray')

    def load_new_image(self, window, just_started=False, force_new_tag_set=False):
        self.make_preview_image_transparent(window)
        result = ImageFetchResponse.REACHED_END if force_new_tag_set or (just_started and not self.at_last_post) else self.fetch_image()
        old_tag_set_num = self.current_tag_set_num
        while result == ImageFetchResponse.REACHED_END or result == ImageFetchResponse.FETCH_ERROR:
            if result == ImageFetchResponse.REACHED_END:
                # Move onto next tag set if last post has been reached, or if it's not a new post
                if self.continuing_from_checkpoint:
                    self.remove_tag_set_checkpoint(self.tag_sets[self.current_tag_set_num])
                    self.at_checkpoint = False
                    self.continuing_from_checkpoint = False
                    print('Checkpoint ended')

                self.at_last_post = False
                self.continuing_from_last_post = False
                if not just_started:
                    self.current_tag_set_num = (self.current_tag_set_num + 1) % len(self.tag_sets)
                    if self.current_tag_set_num == old_tag_set_num:
                        sg.popup_ok('There are no new posts for any of your tag sets, the program will now close.')
                        exit()
                just_started = False

                if old_tag_set_num < 0:
                    # If old tag set number was -1 because it was from the previous session, correct it
                    old_tag_set_num = self.current_tag_set_num
                self.current_image_num = 0

                if self.tag_sets[self.current_tag_set_num] in self.tag_set_checkpoints:
                    self.at_checkpoint = True
                    self.continuing_from_checkpoint = True
            else:
                # Failed to load image, just move onto the next one
                self.current_image_num += 1
            result = self.fetch_image()

        full_url, sample_url = result
        print(full_url, self.post_id)
        self.display_image(full_url, sample_url, window)
        self.current_image_num += 1

    def fetch_image(self):
        tags = f'id:{self.last_post["post_id"]}' if self.at_last_post \
            else self.last_post['tag_set'] if self.continuing_from_last_post \
            else f'id:{self.tag_set_checkpoints[self.tag_sets[self.current_tag_set_num]]}' if self.at_checkpoint \
            else self.tag_sets[self.current_tag_set_num]
        blacklist_tags = ' '.join(f'-{tag}' for tag in self.blacklist)
        page = 1 if self.at_last_post or self.at_checkpoint \
            else f'b{self.last_post["post_id"]}' if self.continuing_from_last_post \
            else f'b{self.checkpoint_previous_post_id}' if self.continuing_from_checkpoint \
            else self.current_image_num + 1
        args = {
            'limit': 1,
            'tags': f'{tags} order:id_desc -type:swf -type:webm {blacklist_tags}',
            'page': page
        }

        result = requests.get('https://e621.net/posts.json', params=args, headers={ 'User-Agent': 'e621 Save Assistant' })
        print(result.json(), result.status_code)
        if result.status_code != 200:
            return ImageFetchResponse.FETCH_ERROR
        if len(result.json()['posts']) == 0:
            return ImageFetchResponse.REACHED_END
            
        post = result.json()['posts'][0]
        full_url = post['file']['url']
        sample_url = post['sample']['url']
        self.image_extension = post['file']['ext']
        self.image_artists = ', '.join(post['tags']['artist'])
        self.post_id = post['id']

        if tags in self.latest_posts and self.latest_posts[tags] == full_url:
            return ImageFetchResponse.REACHED_END
        if not self.continuing_from_last_post and self.current_image_num == 0:
            self.latest_posts[tags] = full_url
        util.save_json_file(self.LATEST_POSTS_FILENAME, self.latest_posts)

        if not self.at_last_post:
            self.last_post = { 'tag_set': tags, 'post_id': self.post_id }
            util.save_json_file(self.LAST_POST_FILENAME, self.last_post)
        self.at_last_post = False
        self.at_checkpoint = False

        if self.continuing_from_checkpoint:
            self.checkpoint_previous_post_id = self.post_id

        if full_url is None: # Can, for example, happen when accessing an image that requires a login
            return ImageFetchResponse.FETCH_ERROR
        
        return full_url, sample_url

    def display_image(self, full_url, sample_url, window):
        self.get_image(full_url, is_full=True)
        sample_image = self.get_image(sample_url, is_full=False)

        self.preview_image = self.get_resized_image(window, sample_image, self.image_height)
        is_gif = self.update_preview_image(window, self.preview_image)

        full_size = round(os.path.getsize(self.full_image_filename) / 1024)
        sample_size = round(os.path.getsize(self.sample_image_filename) / 1024)
        artist_text = f'Artist(s): {self.image_artists} {" (animated GIF)" if is_gif else ""}'
        window['currenttagset'].update(f'Tags: {self.tag_sets[self.current_tag_set_num]}')
        window['artist'].update(artist_text)
        window['savefull'].update(text=f'Save full ({full_size} kB)')
        window['savesample'].update(text=f'Save sample ({sample_size} kB)')

    def update_preview_image(self, window, image):
        is_gif = (self.image_extension.lower() == 'gif')
        image_format = 'GIF' if is_gif else 'PNG'
        bytes_io = io.BytesIO()
        image.save(bytes_io, format=image_format) # PySimpleGUI doesn't support JPG, so convert to PNG
        window['image'].update(data=bytes_io.getvalue())
        return is_gif

    def get_image(self, url, is_full):
        response = requests.get(url, stream=True)
        response.raw.decode_content = True
        if is_full:
            self.full_image_filename = f'{self.TEMP_IMAGE_FOLDER}/tempfull.{self.image_extension}'
            filename = self.full_image_filename
        else:
            self.sample_image_filename = f'{self.TEMP_IMAGE_FOLDER}/tempsample.{self.image_extension}'
            filename = self.sample_image_filename

        with open(filename, 'wb') as f:
            f.write(response.raw.read())
        return Image.open(filename)

    def get_resized_image(self, window, image, height):
        width = int(min(image.width / image.height * height, window.size[0] * self.MAX_IMAGE_WIDTH))
        height = int(width * image.height / image.width)
        size = (width, height)
        return image.resize(size, resample=Image.Resampling.BICUBIC)

    def save_image(self, is_full):
        src_filename = self.full_image_filename if is_full else self.sample_image_filename
        dest_filename = f'{self.settings["output_folder"]}/{self.find_save_image_number()}.{self.image_extension}'
        print(dest_filename)
        shutil.copyfile(src_filename, dest_filename)

    def make_preview_image_transparent(self, window):
        if self.preview_image is None: return
        image = self.preview_image.convert('RGBA')
        transparent_data = [ (r, g, b, a // 2) for r, g, b, a in image.getdata() ]
        image.putdata(transparent_data)
        self.update_preview_image(window, image)
        window.refresh()

    def add_tag_set_checkpoint(self):
        tag_set = self.tag_sets[self.current_tag_set_num]
        self.tag_set_checkpoints[tag_set] = self.post_id
        util.save_json_file(self.TAG_SET_CHECKPOINTS_FILENAME, self.tag_set_checkpoints)

    def remove_tag_set_checkpoint(self, tag_set):
        try:
            del self.tag_set_checkpoints[tag_set]
        except KeyError:
            pass

        util.save_json_file(self.TAG_SET_CHECKPOINTS_FILENAME, self.tag_set_checkpoints)

    def clear_last_post(self):
        try:
            self.last_post = {}
            os.remove('./last_post.json')
        except OSError:
            pass

    def find_save_image_number(self):
        largest_image_number = None
        output_folder = self.settings['output_folder']
        filenames = [ f for f in os.listdir(output_folder) if os.path.isfile(os.path.join(output_folder, f)) ]
        for filename in filenames:
            filename_without_extension = '.'.join(filename.split('.')[:-1])
            try:
                image_number = int(filename_without_extension)
                if largest_image_number is None:
                    largest_image_number = image_number
                else:
                    largest_image_number = max(largest_image_number, image_number)
            except ValueError:
                continue

        return 1 if largest_image_number is None else largest_image_number + 1

    def resize_elements(self, window):
        # At first this also resized buttons and text, but it just didn't look very good
        # Therefore it only resizes the image
        self.image_height = max(self.MIN_IMAGE_HEIGHT, round(window.size[1] * self.IMAGE_WINDOW_HEIGHT_MULTIPLIER))

if __name__ == '__main__':
    curator = Curator()
    curator.run()