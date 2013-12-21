import os
import re
import sublime
import sublime_plugin
import subprocess
import threading

if int(sublime.version()) < 3000:
    from sublime_haskell_common import *
    from ghci import parse_info
    from parseoutput import parse_output_messages, show_output_result_text, format_output_messages, mark_messages_in_views, hide_output, set_global_error_messages
    import symbols
else:
    from SublimeHaskell.sublime_haskell_common import *
    from SublimeHaskell.ghci import parse_info
    import SublimeHaskell.symbols as symbols
    from SublimeHaskell.parseoutput import parse_output_messages, show_output_result_text, format_output_messages, mark_messages_in_views, hide_output, set_global_error_messages


def show_hdevtools_error_and_disable():
    # Looks like we can't always get an active window here,
    # we use sublime.error_message() instead of
    # output_error(sublime.active_window().
    sublime.set_timeout(lambda: sublime.error_message(
        "SublimeHaskell: hdevtools was not found!\n"
        + "It's used for 'symbol info' and type inference\n"
        + "Install it with 'cabal install hdevtools',\n"
        + "or adjust the 'add_to_PATH' setting for a custom location.\n"
        + "'enable_hdevtools' automatically set to False in the User settings."), 0)

    set_setting_async('enable_hdevtools', False)

def hdevtools_binary_and_library_dir():
    # current_project_dir, current_project_name = get_cabal_project_dir_and_name_of_view(self.window.active_view())
    window, view, file_shown_in_view = get_haskell_command_window_view_file_project()
    sandbox_path = find_file_in_parent_dir(os.path.dirname(file_shown_in_view), '.cabal-sandbox', filter=os.path.isdir)

    if (sandbox_path is not None):
        putative_binary = os.path.join(sandbox_path, 'bin/hdevtools')
        librarydirs = fnmatch.filter(os.listdir(sandbox_path), "*-packages.conf.d")
        if len(librarydirs) == 0:
            librarydir = None
        elif len(librarydirs) == 1:
            librarydir = librarydirs[0]
        else:
            log("Curious. More than one library dir in %s" % (sandbox_path,))
            librarydir = librarydirs[0]
        if os.path.exists(putative_binary):
            # log("using " + putative_binary)
            return putative_binary, librarydir

    return 'hdevtools', librarydir

def call_hdevtools_and_wait(arg_list, filename = None, cabal = None):
    """
    Calls hdevtools with the given arguments.
    Shows a sublime error message if hdevtools is not available.
    """
    if not hdevtools_enabled():
        log("call_hdevtools_and_wait: hdevtools disabled")
        return None

    ghc_opts_args = get_ghc_opts_args(filename, cabal = cabal)
    hdevtools_socket = get_setting_async('hdevtools_socket')
    source_dir = get_source_dir(filename)

    if hdevtools_socket:
        arg_list.append('--socket={0}'.format(hdevtools_socket))
    hdevtools_binary, librarydir = hdevtools_binary_and_library_dir()
    if librarydir is not None:
        arg_list.append('-g -package-db={0}'.format(librarydir))

    log(hdevtools_binary)
    log(arg_list)
    log(ghc_opts_args)
    try:
        exit_code, out, err = call_and_wait([hdevtools_binary] + arg_list + ghc_opts_args, cwd = source_dir)

        if err:
            raise Exception("hdevtools exited with status %d and stderr: %s" % (exit_code, err))

        return parse_output_messages(source_dir, out)

    # except OSError as e:
    #     if e.errno == errno.ENOENT:
    #         show_hdevtools_error_and_disable()

    #     return None

    except Exception as e:
        log('calling to hdevtools fails with {0}'.format(e))
        return None

def admin(cmds, wait = False, **popen_kwargs):
    if not hdevtools_enabled():
        return None

    hdevtools_socket = get_setting_async('hdevtools_socket')

    if hdevtools_socket:
        cmds.append('--socket={0}'.format(hdevtools_socket))

    command = [hdevtools_binary_and_library_dir()[0], "admin"] + cmds

    try:
        if wait:
            (exit_code, stdout, stderr) = call_and_wait(command, **popen_kwargs)
            if exit_code == 0:
                return stdout
            return ''
        else:
            call_no_wait(command, **popen_kwargs)
            return ''

    except OSError as e:
        if e.errno == errno.ENOENT:
            show_hdevtools_error_and_disable()

        set_setting_async('enable_hdevtools', False)

        return None
    except Exception as e:
        log('calling to hdevtools fails with {0}'.format(e))
        return None

def is_running():
    r = admin(['--status'], wait = True)
    if r and re.search(r'running', r):
        return True
    else:
        return False

def start_server():
    if not is_running():
        admin(["--start-server"])

def hdevtools_info(filename, symbol_name, cabal = None):
    """
    Uses hdevtools info filename symbol_name to get symbol info
    """
    contents = call_hdevtools_and_wait(['info', filename, symbol_name], filename = filename, cabal = cabal)
    return parse_info(symbol_name, contents) if contents else None

def hdevtools_check(filename, cabal = None):
    """
    Uses hdevtools to check file
    """
    return call_hdevtools_and_wait(['check', filename], filename = filename, cabal = cabal)

def hdevtools_type(filename, line, column, cabal = None):
    """
    Uses hdevtools to infer type
    """
    return call_hdevtools_and_wait(['type', filename, str(line), str(column)], filename = filename, cabal = cabal)

def start_hdevtools():
    thread = threading.Thread(
        target=start_server)
    thread.start()

def stop_hdevtools():
    admin(["--stop-server"])

def hdevtools_enabled():
    return get_setting_async('enable_hdevtools') == True

class SublimeHaskellHdevtoolsCheck(sublime_plugin.WindowCommand):
    def run(self):
        window, view, file_shown_in_view = get_haskell_command_window_view_file_project()
        if not file_shown_in_view:
            return

        file_dir, file_name = os.path.split(file_shown_in_view)
        log('hdevtools checking ' + file_shown_in_view)
        parsed_output = hdevtools_check(file_shown_in_view)
        if parsed_output is None:
            raise ValueError, "hdevtools failed!"
        log(parsed_output)
        set_global_error_messages(parsed_output)
        sublime.set_timeout(lambda: mark_messages_in_views(parsed_output), 0)
        output_text = "\n".join([p.message for p in parsed_output])
        exit_code = 1 if parsed_output else 0
        show_output_result_text(view, '', output_text, exit_code, file_dir)



    def is_enabled(self):
        return is_haskell_source(None)
