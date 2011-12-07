"""
Playing with ncurses in Python to scroll up and down, left and right, through a list of data that is periodically refreshed. 

Revs:
2010-12-11  JRM Added concat for status line to prevent bailing on small terminals.
                Code cleanup to prevent modification of external variables.
                Added left,right page controls
"""

import curses, sys, types

class Scroll:

    # what should be printed at the bottom of the screen?
    instructionString = ""

    # at which row and col must we draw the screen output?
    offsetV = 0
    offsetH = 0
    
    # the main screen object
    screen = None

    # the line position at which we're currently drawing
    currentLinePosition = 0
    currentXPosition = 0

    # set up the screen
    def screenSetup(self):
        self.screen = curses.initscr()
        self.screen.keypad(1)
        #curses.start_color() #this doesn't seem to work properly
        self.screen.nodelay(1)
        curses.noecho()
        curses.cbreak()

    # restore sensible options to the terminal 
    def screenTeardown(self):
        curses.nocbreak()
        curses.echo()
        curses.endwin()

    # act on certain keys
    def processKeyPress(self):
        key = self.screen.getch()
        if key > 0: 
            if chr(key) == 'q': raise KeyboardInterrupt		# q for quit
            elif chr(key) == 'u': self.offsetV -= curses.LINES 
            elif chr(key) == 'd': self.offsetV += curses.LINES  
            elif chr(key) == 'l': self.offsetH += curses.COLS  
            elif chr(key) == 'r': self.offsetH -= curses.COLS 
            elif chr(key) == 'h': self.offsetH = 0; self.offsetV=0 
            elif key == 65: self.offsetV -= 1               # up
            elif key == 66: self.offsetV += 1               # down
            elif key == 67: self.offsetH -= 1               # right
            elif key == 68: self.offsetH += 1               # left
            return [key,chr(key)]
        else:
            return [0,chr(0)]

    # clear the screen
    def clearScreen(self):
        self.screen.clear()

    # draw a new line to the screen, takes an argument as to whether the screen should be immediately refreshed or not
    def drawString(self, newLine, **kwargs):
        try: 
            refresh=kwargs.pop('refresh')
        except:
            refresh=False
            pass
        self.screen.addstr(self.currentLinePosition, self.currentXPosition, newLine,**kwargs)
        if newLine.endswith('\n'):
            self.currentLinePosition += 1
            self.currentXPosition = 0
        else:
            self.currentXPosition += len(newLine)
        if refresh: self.screen.refresh()

    # draw the screen
    def drawScreen(self, data,lineattrs=None):
        # clear the screen
        self.screen.clear()
        numLinesTotal = len(data)
        # reserve the bottom three lines for instructions
        numLinesAvailable = curses.LINES -1 
        # can we fit everything on the screen?
        topLine = 0
        if numLinesTotal > numLinesAvailable:
            topLine = numLinesTotal - numLinesAvailable
        # check the offsets, vertical and horizontal
        self.offsetV = min(0, self.offsetV)
        self.offsetV = max(-1 * topLine, self.offsetV)
        self.offsetH = min(0, self.offsetH)
        # which line are we showing at the top?
        topLine += self.offsetV
        topLine = max(topLine, 0)
        bottomLine = min(numLinesTotal, topLine + numLinesAvailable)
        # add the lines to the curses screen one by one
        self.currentLinePosition = 0
        for lineNum in range(topLine, bottomLine):
            #data[lineNum] = "%03i-%03i-%03i-%03i-" % (topLine, lineNum, self.offsetV, self.offsetH) + data[lineNum]
            # truncate long lines and add the data to the screen
            if (lineattrs==None):# or (len(lineattrs) != len(data)):
                attr = [curses.A_NORMAL] 
            elif (type(lineattrs[lineNum]) == types.ListType):
                attr = lineattrs[lineNum]
            else:
                attr = [lineattrs[lineNum]]
            self.screen.addstr(self.currentLinePosition, 
                                0, 
                                (data[lineNum][-1 * self.offsetH:(-1 * self.offsetH) + curses.COLS]) + '\n',
                                *attr)
            self.currentLinePosition += 1
        stat_line="Showing line %i to %i of %i. Column offset %i. %s Scroll with arrow keys. u,d,l,r=page up, down, left and right. h=home, q=quit." % (topLine, bottomLine, numLinesTotal, self.offsetH, self.instructionString)
        stat_line=stat_line[-1 * self.offsetH:(-1 * self.offsetH) + (curses.COLS-1)]
        self.screen.addstr(numLinesAvailable, 0, stat_line,curses.A_REVERSE)
        self.screen.refresh()

    # set and get the instruction string at the bottom
    def getInstructionString(self):
        return self.instructionString
    def setInstructionString(self, newString):
        self.instructionString = newString

# end of file

