"""
Wordpress client
"""

from urllib.parse import urlparse

import os.path
import mimetypes
import requests
from readability.readability import Document, Unparseable
from wordpress_xmlrpc import Client, WordPressPost
from wordpress_xmlrpc.compat import xmlrpc_client
from wordpress_xmlrpc.methods import media, posts

from feedspora.generic_client import GenericClient


class WPClient(GenericClient):
    ''' The WPClient handles the connection to Wordpress. '''
    client = None

    def __init__(self, account, testing):
        '''
        Initialize
        :param account:
        :param testing:
        '''
        self._account = account

        if not testing:
            self.client = Client(account['wpurl'], account['username'],
                                 account['password'])
        self.set_common_opts(account)

    # pylint: disable=no-self-use
    def get_content(self, url):
        '''
        Retrieve URL content and parse it w/ readability if it's HTML
        :param url:
        '''
        request = requests.get(url)
        content = ''

        # pylint: disable=no-member

        if request.status_code == requests.codes.ok and \
           request.headers['Content-Type'].find('html') != -1:
            try:
                content = Document(request.text).summary()
            except Unparseable:
                pass
        # pylint: enable=no-member

        return content
    # pylint: enable=no-self-use

    def get_dict_output(self, **kwargs):
        '''
        Return dict output for testing purposes
        :param kwargs:
        '''

        return {
            "client": self._account['name'],
            "title": self._account['post_prefix']+kwargs['entry'].title + \
                     self._account['post_suffix'],
            "post_tag": self.filter_tags(kwargs['entry']),
            "media_path": kwargs['media_path'],
            "Content": self.shorten_url(kwargs['entry'].link)
        }

    def post(self, entry):
        '''
        Post entry to Wordpress.
        :param entry:
        '''

        def get_mimetype(media_path):
            '''
            Determine/return the mimetype of the specified file path object
            '''

            to_return = ''
            try:
                to_return = mimetypes.read_mime_types(media_path)
            except UnicodeDecodeError:
                to_return = mimetypes.guess_type(media_path)[0]

            return to_return


        def upload_media(media_path):
            '''
            Upload the media using XML-RPC mechanisms
            :param media_path:
            '''
            # prepare metadata
            upload_data = {'name': os.path.basename(media_path),
                           'type': get_mimetype(media_path)
                           }

            # Read the binary file and let the XMLRPC library encode it
            # into base64
            with open(media_path, 'rb') as img:
                upload_data['bits'] = xmlrpc_client.Binary(img.read())

            response = self.client.call(media.UploadFile(upload_data))

            return response['id']

        article_content = ''
        if 'post_use_feed_data' in self._account and \
           self._account['post_use_feed_data']:
            if self._account['post_include_content'] and entry.content:
                article_content = self.strip_html(entry.content)
        else:
            article_content = self.get_content(entry.link)

        post_content = r"Source: <a href='{}'>{}</a><hr\>{}".format(
            self.shorten_url(entry.link),
            urlparse(entry.link).netloc, article_content)

        # Resolve media, if appropriate and possible
        media_path = None
        if self._account['post_include_media'] and entry.media_url:
            # Need to download image from that URL in order to post it!
            media_path = self.download_media(entry.media_url)

        to_return = False
        if self.is_testing():
            self.accumulate_testing_output(
                self.get_dict_output(entry=entry, media_path=media_path))
        else:
            # Upload media, if appropriate
            attachment_id = 0
            if media_path:
                attachment_id = upload_media(media_path)

            # get text with readability
            post = WordPressPost()
            post.title = self._account['post_prefix']+entry.title + \
                         self._account['post_suffix']
            post.content = post_content
            post.terms_names = {
                'post_tag': self.filter_tags(entry),
                'category': ["AutomatedPost"]
            }
            post.post_status = 'publish'
            if attachment_id:
                post.thumbnail = attachment_id
            post_id = self.client.call(posts.NewPost(post))
            to_return = post_id != 0

        return to_return
