import shutil


def print_clean(msg):
    terminal_size = shutil.get_terminal_size()
    msg_length = len(msg)
    print("{}{}".format(msg, " " * (int(terminal_size[0]) - msg_length)), end='')
