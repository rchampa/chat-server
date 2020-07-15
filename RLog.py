RLOGS_ENABLE = True


def rprint(*args, sep=' ', end='\n', file=None) -> None:
    if RLOGS_ENABLE:
        print(args, sep=sep, end=end, file=file)
