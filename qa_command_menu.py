from command_menu_patch import parse_command, menu_text


def main():
    assert parse_command('/menu') == ('/menu', '')
    assert parse_command('/sources') == ('/sources', '')
    assert parse_command('/sources@movieskhbot') == ('/sources', 'movieskhbot')
    assert parse_command('/update@MoviesKhBot extra') == ('/update', 'movieskhbot')
    assert parse_command('hello') == ('', '')

    text = menu_text()
    for cmd in ('/menu', '/update', '/status', '/sources', '/help'):
        assert cmd in text, cmd

    print('PASS: /menu supported')
    print('PASS: bare commands supported')
    print('PASS: @botusername command parsing supported')
    print('PASS: menu contains all production commands')


if __name__ == '__main__':
    main()
