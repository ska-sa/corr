# pylint: disable-msg=C0301
# pylint: disable-msg=E1101
"""
Playing with ncurses in Python to scroll up and down, left and right, through a list of data that is periodically refreshed.

Revs:
2010-12-11  JRM Added concat for status line to prevent bailing on small terminals.
                Code cleanup to prevent modification of external variables.
                Added left, right page controls
"""

import curses, types

def screen_teardown():
    '''Restore sensible options to the terminal upon exit
    '''
    curses.nocbreak()
    curses.echo()
    curses.endwin()

class Scroll(object):
    '''Scrollable ncurses screen.
    '''

    def __init__(self):
        '''Constructor
        '''
        # what should be printed at the bottom of the screen?
        self.instruction_string = ""

        # at which row and col must we draw the screen output?
        self.offset_y = 0
        self.offset_x = 0

        # the main screen object
        self.screen = None

        # the line position at which we're currently drawing
        self.curr_y_pos = 0
        self.curr_x_pos = 0

    # set up the screen
    def screen_setup(self):
        '''Set up a curses screen object and associated options
        '''
        self.screen = curses.initscr()
        self.screen.keypad(1)
        self.screen.nodelay(1)
        curses.noecho()
        curses.cbreak()

    def on_keypress(self):
        '''
        Handle key presses.
        '''
        key = self.screen.getch()
        if key > 0:
            try:
                if chr(key) ==  'q':
                    raise KeyboardInterrupt		# q for quit
                elif chr(key) ==  'u':
                    self.offset_y -=  curses.LINES
                elif chr(key) ==  'd':
                    self.offset_y +=  curses.LINES
                elif chr(key) ==  'l':
                    self.offset_x +=  curses.COLS
                elif chr(key) ==  'r':
                    self.offset_x -=  curses.COLS
                elif chr(key) ==  'h':
                    self.offset_x = 0
                    self.offset_y = 0
                elif key ==  65:
                    self.offset_y -=  1               # up
                elif key ==  66:
                    self.offset_y +=  1               # down
                elif key ==  67:
                    self.offset_x -=  1               # right
                elif key ==  68:
                    self.offset_x +=  1               # left
                return [key, chr(key)]
            except ValueError:
                return [0, 0]
        else:
            return [0, 0]

    def clear_screen(self):
        '''Clear the ncurses screen.
        '''
        self.screen.clear()

    def draw_string(self, new_line, **kwargs):
        '''Draw a new line to the screen, takes an argument as to whether the screen should be immediately refreshed or not
        '''
        try:
            refresh = kwargs.pop('refresh')
        except:
            refresh = False
        self.screen.addstr(self.curr_y_pos, self.curr_x_pos, new_line, **kwargs)
        if new_line.endswith('\n'):
            self.curr_y_pos +=  1
            self.curr_x_pos = 0
        else:
            self.curr_x_pos +=  len(new_line)
        if refresh:
            self.screen.refresh()

    def draw_screen(self, data, lineattrs = None):
        '''Draw the screen using the provided data
        '''
        # clear the screen
        self.screen.clear()
        num_lines_total = len(data)
        # reserve the bottom three lines for instructions
        num_lines_available = curses.LINES -1
        # can we fit everything on the screen?
        top_line = 0
        if num_lines_total > num_lines_available:
            top_line = num_lines_total - num_lines_available
        # check the offsets, vertical and horizontal
        self.offset_y = min(0, self.offset_y)
        self.offset_y = max(-1 * top_line, self.offset_y)
        self.offset_x = min(0, self.offset_x)
        # which line are we showing at the top?
        top_line +=  self.offset_y
        top_line = max(top_line, 0)
        bottom_line = min(num_lines_total, top_line + num_lines_available)
        # add the lines to the curses screen one by one
        self.curr_y_pos = 0
        for line_num in range(top_line, bottom_line):
            #data[line_num] = "%03i-%03i-%03i-%03i-" % (top_line, line_num, self.offset_y, self.offset_x) + data[line_num]
            # truncate long lines and add the data to the screen
            if (lineattrs == None):# or (len(lineattrs) !=  len(data)):
                attr = [curses.A_NORMAL]
            elif (type(lineattrs[line_num]) ==  types.ListType):
                attr = lineattrs[line_num]
            else:
                attr = [lineattrs[line_num]]
            self.screen.addstr(self.curr_y_pos,
                                0,
                                (data[line_num][-1 * self.offset_x:(-1 * self.offset_x) + curses.COLS]) + '\n',
                                *attr)
            self.curr_y_pos +=  1
        stat_line = "Showing line %i to %i of %i. Column offset %i. %s Scroll with arrow keys. u, d, l, r = page up, down, left and right. h = home, q = quit." % (top_line, bottom_line, num_lines_total, self.offset_x, self.instruction_string)
        stat_line = stat_line[-1 * self.offset_x:(-1 * self.offset_x) + (curses.COLS-1)]
        self.screen.addstr(num_lines_available, 0, stat_line, curses.A_REVERSE)
        self.screen.refresh()

    # set and get the instruction string at the bottom
    def get_instruction_string(self):
        return self.instruction_string
    def set_instruction_string(self, new_string):
        self.instruction_string = new_string

# end of file
