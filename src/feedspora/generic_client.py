"""
GenericClient: baseclass providing features to specific clients.
"""

import logging
import os
import posixpath
import re
import mimetypes
import urllib.parse
import urllib.request
import lxml.html
import pyshorteners

from feedspora.common_config import CommonConfig

class GenericClient(CommonConfig):
    ''' Implements the base functionalities expected from clients '''

    _testing_root = None
    _testing_output = None

    def post(self, entry):
        '''
        Placeholder for post, override it in subclasses
        :param entry:
        '''
        raise NotImplementedError("Please implement!")

    def set_testing_root(self, testing_root):
        '''
        Client testing_root setter
        :param testing_root:
        '''
        self._testing_root = testing_root

    def get_testing_root(self):
        '''
        Client testing_root getter
        '''

        return self._testing_root

    def is_testing(self):
        '''
        Are we testing this client?
        '''

        return self._testing_root is not None

    def accumulate_testing_output(self, outdict):
        '''
        Record output for testing purpose
        '''

        if not self._testing_output:
            self._testing_output = []
        self._testing_output.append(outdict)

    def pop_testing_output(self):
        '''
        Retrieve output and clear it for the next round
        '''
        to_return = self._testing_output
        self._testing_output = []

        return to_return

    def get_dict_output(self, **kwargs):
        '''
        Define output for testing purposes (potentially overridden on
        per-client basis - this is the default), then output that definition
        :param kwargs:
        '''

        return {"client": self._config['name'], "content": kwargs['text']}

    # pylint: disable=no-self-use
    def _trim_string(self, text, maxlen, etc='...', etc_if_shorter_than=None):
        '''
        Trim the string to the specified length, using the etc notation to show
        this has been done
        :param text:
        :param maxlen:
        :param etc:
        :param etc_if_shorter_than:
        '''

        if len(text) < maxlen:
            to_return = text
        else:
            tmpmaxlen = maxlen - len(etc)
            space_pos = [
                x for x in range(0, len(text))

                if text[x] == ' ' and x < tmpmaxlen
            ]
            cut_at = space_pos[-1] if space_pos else tmpmaxlen
            to_return = text[:cut_at]

            if etc_if_shorter_than and cut_at < etc_if_shorter_than:
                to_return += etc

        return to_return
    # pylint: enable=no-self-use

    # pylint: disable=too-many-locals
    # pylint: disable=too-many-arguments
    # pylint: disable=no-self-use
    def _mkrichtext(self,
                    text,
                    tags,
                    maxlen=None,
                    etc='...',
                    separator=' |'):
        '''
        Process the text to include hashtags and adhere to the
        specified maximum length.
        :param text:
        :param tags:
        :param maxlen:
        :param etc:
        :param separator:
        '''

        def repl(match):
            return '%s#%s%s' % (match.group(1), match.group(2), match.group(3))

        # Constants used in regex pattern generation
        # pylint: disable=anomalous-backslash-in-string
        before_tag = r'(\A|[\'"/([{\s])'
        after_tag = r'(\Z|[\'"/\s)\]},.!?:])'
        # pylint: enable=anomalous-backslash-in-string

        to_return = text

        # Tag order needs to be observed
        # Set manipulations ignore that, so use lists instead!

        # Find inline and extra tags
        inline_kw = []
        extra_kw = []

        for word in tags:
            # remove any illegal characters
            word = re.sub(r'[\-\.]', '', word)

            if re.search(
                    r'%s#?(%s)%s' % (before_tag, re.escape('%s' % word),
                                     after_tag), to_return, re.IGNORECASE):
                inline_kw.append(word)
            else:
                extra_kw.append(word)

        # Process inline tags
        for word in inline_kw:
            pattern = (
                r'%s(%s)%s' % (before_tag, re.escape('%s' % word), after_tag))

            if re.search(pattern, to_return, re.IGNORECASE):
                to_return = re.sub(
                    pattern, repl, to_return, flags=re.IGNORECASE)

        # Add separator and tags, if needed
        minlen_wo_xtra_kw = len(to_return)

        if extra_kw:
            fake_separator = separator.replace(' ', '_')
            to_return += fake_separator
            minlen_wo_xtra_kw = len(to_return)

            # Add extra (ordered) tags
            for word in extra_kw:
                # prevent duplication
                pattern = (r'%s#(%s)%s' % (before_tag, re.escape('%s' % word),
                                           after_tag))

                if re.search(pattern, to_return, re.IGNORECASE) is None:
                    to_return += " #" + word

        # If the text is too long, cut it and, if needed, add suffix
        if maxlen is not None:
            to_return = self._trim_string(
                to_return,
                maxlen,
                etc=etc,
                etc_if_shorter_than=minlen_wo_xtra_kw)

        # Restore separator
        if extra_kw:
            to_return = to_return.replace(fake_separator, separator)

            # Remove separator if nothing comes after it
            stripped_separator = separator.rstrip()

            if to_return.endswith(stripped_separator):
                to_return = to_return[:-len(stripped_separator)]

        if maxlen is not None:
            assert not len(to_return) > maxlen, \
                "{}:{} : {} > {}".format(text, to_return, len(to_return),
                                         maxlen)

        return to_return
    # pylint: enable=no-self-use
    # pylint: enable=too-many-locals
    # pylint: enable=too-many-arguments

    # pylint: disable=no-self-use
    def get_mimetype(self, media_path):
        '''
        Determine/return the mimetype of the specified file path object
        :param media_path:
        '''

        to_return = ''
        try:
            to_return = mimetypes.read_mime_types(media_path)
        except UnicodeDecodeError:
            to_return = mimetypes.guess_type(media_path)[0]

        return to_return
    # pylint: enable=no-self-use


    # pylint: disable=no-self-use
    def download_media(self, the_url):
        '''
        Download the media file referenced by the_url
        Returns the path to the downloaded file
        :param the_url:
        '''

        def get_filename_from_cd(content_disp):
            '''
            Get filename from Content-Disposition
            :param content_disp:
            '''

            to_return = None

            if content_disp:
                fname = re.findall('filename=(.+)', content_disp)

                if fname:
                    to_return = fname[0]

            return to_return


        def get_filename_from_response(the_response):
            '''
            Attempt to get the filename from the response
            :param the_response:
            '''

            url_parts = urllib.parse.urlparse(the_response.geturl())
            to_return = posixpath.basename(url_parts.path)
            # Sanity check
            if not re.match(r'^[\w-]+\.(jpg|jpeg|gif|png)$',
                            to_return, re.IGNORECASE):
                # Nope, "bad" filename
                logging.error("Invalid media filename '%s' - ignoring",
                              to_return)
                to_return = ''

            return to_return

        request = urllib.request.Request(the_url)
        request.add_header('User-Agent', 'Mozilla/5.0')
        response = urllib.request.urlopen(request)
        filename = get_filename_from_cd(
            request.get_header('Content-Disposition')) or \
            get_filename_from_response(response) or \
            'random.jpg'

        media_dir = os.getenv('MEDIA_DIR', '/tmp')
        full_path = media_dir + '/' + filename
        logging.info("Downloading %s as %s...", the_url, full_path)
        with open(full_path, 'wb') as file_chunk:
            file_chunk.write(response.read())

        return full_path
    # pylint: enable=no-self-use

    def strip_html(self, before_strip):
        '''
        Strip HTML from the content
        :param before_strip:
        '''

        to_return = None
        # Getting the stripped HTML might take multiple attempts
        done = False
        while not done:
            to_return = lxml.html.fromstring(
                before_strip).text_content().strip()
            done = to_return == before_strip
            if not done:
                before_strip = to_return
        # Remove all tags from end of content!
        to_return = self.remove_ending_tags(to_return)

        return to_return

    # TODO: Move and enhance all of below
    def post_within_limits(self, entry_to_post):
        '''
        Client post entry, as long as within specified limits
        :param entry_to_post:
        TODO: Move this to FeedSpora, include feed config
        '''
        to_return = False

        if not self.is_post_limited() or \
           self._posts_done < self._config['max_posts']:
            to_return = self.post(entry_to_post)

            if to_return:
                self._posts_done += 1

        return to_return

    def seeding_published_db(self, item_num):
        '''
        Override to post not being published, but marking it as published
        in the DB anyway ("seeding" the published DB)
        :param item_num:
        TODO: Move this to FeedSpora, include feed config
        '''

        return self._config['max_posts'] < 0 and item_num + self._config['max_posts'] <= 0

    def shorten_url(self, the_url):
        '''
        Apply configured URL shortener (if present) to the provided link and
        return the result.  If anything goes awry, return the unmodified link.
        :param the_url:
        TODO: Move this to FeedSpora, include feed config
        '''
        to_return = the_url
        # Default
        short_options = {'timeout': 3}
        if 'url_shortener_opts' in self._config:
            short_options.update(self._config['url_shortener_opts'])

        if the_url and 'url_shortener' in self._config and \
           self._config['url_shortener'] != 'none':
            try:
                shortener = pyshorteners.Shortener(**short_options)
                # Verify a legal choice
                # pylint: disable=no-member
                assert self._config['url_shortener'] in \
                    shortener.available_shorteners
                # pylint: enable=no-member
                to_return = getattr(
                    shortener, self._config['url_shortener']).short(the_url)
                # Sanity check!

                if len(to_return) > len(the_url):
                    # Not shorter?  You're fired!
                    raise RuntimeError(
                        'Shortener %s produced a longer URL ' +
                        'than the original!', self._config['url_shortener'])
            # pylint: disable=broad-except
            except Exception as exception:
                # Shortening attempt failed somehow (we don't care how, except
                # for messaging purposes) - revert to non-shortened link

                if isinstance(exception, AssertionError):
                    all_shorteners = ' '.join(shortener.available_shorteners)
                    logging.error('URL shortener %s is unimplemented!',
                                  self._config['url_shortener'])
                    logging.info('Available URL shorteners: %s',
                                 all_shorteners)
                else:
                    logging.error('Cannot shorten URL %s with %s: %s',
                                  the_url, self._config['url_shortener'],
                                  str(exception))
                to_return = the_url
            # pylint: enable=broad-except

        return to_return

    def filter_tags(self, entry):
        '''
        Filter the client-specific tag list and entry tag lists
        (title, content, category) according to the client-specific tag
        filtering options, producing an ordered and size-limited tag list
        to be used during posting
        :param entry:
        TODO: Move this to FeedSpora, include feed config
        '''

        # First priority: user-defined tags
        to_filter = self._config['tags'][:] if self._config['tags'] else []
        # Next, title tags, if appropriate
        if (not (self._config['tag_filter_opts'] and
                 'ignore_title' in self._config['tag_filter_opts'])) and \
           entry.tags['title']:
            to_filter.extend(entry.tags['title'])
        # Then, content tags, if appropriate
        if (not (self._config['tag_filter_opts'] and
                 'ignore_content' in self._config['tag_filter_opts'])) and \
           entry.tags['content']:
            to_filter.extend(entry.tags['content'])
        # Finally, category tags, again if appropriate
        if (not (self._config['tag_filter_opts'] and
                 'ignore_category' in self._config['tag_filter_opts'])) and \
           entry.tags['category']:
            to_filter.extend(entry.tags['category'])

        # And now we filter.  We NEVER want any duplicates, and that might
        # include non-case-sensitive duplication too, depending upon options
        to_return = []
        non_case_sensitive = []
        for tag in to_filter:
            if self._config['tag_filter_opts'] and \
               'case-sensitive' in self._config['tag_filter_opts'] and \
               tag not in to_return:
                to_return.append(tag)
            elif (not (self._config['tag_filter_opts'] and
                       'case-sensitive' in \
                       self._config['tag_filter_opts'])) and \
                 tag.lower() not in non_case_sensitive:
                to_return.append(tag)
                non_case_sensitive.append(tag.lower())
            # We may have all that were specified
            if len(to_return) >= self._config['max_tags']:
                break

        return to_return

    def remove_ending_tags(self, content):
        '''
        Trim any tags from the end of content, and return the modified content,
        unless the ignore_content tag filter option is set (then do nothing).
        :param content:
        TODO: Move this to FeedSpora, include feed config
        '''

        if content and (not
                        (self._config['tag_filter_opts'] and \
                         'ignore_content' in self._config['tag_filter_opts'])):
            tag_pattern = r'\s+#([\w]+)$'
            match_result = re.search(tag_pattern, content)

            while match_result:
                content = re.sub(tag_pattern, '', content)
                match_result = re.search(tag_pattern, content)

            if re.match(r'^\s*#[\w]+$', content):
                # Left with a single tag!
                content = ''

        return content
