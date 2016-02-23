#!/usr/bin/env python

import argparse
import base64
import getpass
import os
import re
import sys
import shutil
import subprocess
import tempfile
import urllib2
import uuid

SOURCE_URL_PREFIX = "https://raw.githubusercontent.com/oxwall/owr/master/sources"
COMPOSER_DOWNLOAD_URL = 'https://getcomposer.org/composer.phar'


def _is_file(file_path):
    return file_path.startswith((".", "..", os.sep, "~"))


def _is_relative_path(file_path):
    return file_path.startswith((".", ".."))


def _is_relative_url(url):
    return not _is_absolute_url(url) and _is_relative_path(url)


def _is_absolute_url(url):
    return url.startswith(("http://", "https://"))


def _change_branch(directory, branch, is_quiet=True):
    quiet = "--quiet" if is_quiet else ""
    os.system(
        ("git --work-tree=%s --git-dir=%s fetch " + quiet + " origin %s") % (
            directory + os.sep, os.path.join(directory, ".git"), branch
        )
    )
    os.system(
        ("git --work-tree=%s --git-dir=%s checkout " + quiet + " origin/%s") % (
            directory + os.sep, os.path.join(directory, ".git"), branch
        )
    )


def _log_operation(operation, repo_url, path, branch):
    colors = {'blue': '\033[94m', 'red': '\033[91m', 'end': '\033[0m'}

    repo_name = repo_url[repo_url.rindex("/") + 1:-4]
    branch_color = colors['blue'] if branch == "master" else colors['red']

    args = (
        colors['blue'] + repo_name + colors['end'],
        branch_color + branch + colors['end'],
        colors['blue'] + path + colors['end']
    )

    if operation == "update":
        print "Updating %s (%s) in %s" % args
    elif operation == "clone":
        print "Cloning %s (%s) to %s" % args


class SourceListParser:
    _sourceListType = "global"

    _defaultConfig = ["github.com/oxwall"]

    _repoSection = {
        "name": "plugins",
        "prefix": None
    }

    records = {}

    def __init__(self, arguments):
        self._arguments = arguments
        self._repoSection["config"] = self._defaultConfig

    def _process_operation(self, command, base_path):
        parts = map(str.strip, command.split(" "))

        g_source_type = self._arguments.sourceType

        def include(source):
            if g_source_type == "file" and _is_file(source):
                path = source
                if _is_relative_path(source):
                    path = os.path.normpath(os.path.join(base_path, source))

                return self._fetch_source(path, "file")

            if _is_absolute_url(source):
                url = source
            elif _is_relative_url(source):
                url = "%s/%s" % (base_path.rstrip("/"), source)
            else:
                url = "%s/%s" % (SOURCE_URL_PREFIX.rstrip("/"), source)

            return self._fetch_source(url, "url")

        operations = {"include": include}

        try:
            operation = operations[parts[0]]
            args = parts[1:]
            operation(*args)
        except (IndexError, KeyError, TypeError):
            return

    def _process_section(self, section):
        parts = map(str.strip, section.split(" "))
        self._repoSection["name"] = parts[0]
        self._repoSection["config"] = parts[1:] if len(parts) > 1 else self._defaultConfig

    def _process_line(self, line):
        parts = map(str.strip, line.split("="))

        name = parts[0]
        try:
            alias = parts[1]
        except IndexError:
            alias = name

        branch = "master"
        reg_exp = re.compile("\((.*)\)")
        args = re.findall(reg_exp, alias)

        if args:
            alias = re.sub(reg_exp, "", alias).strip()
            name = re.sub(reg_exp, "", name).strip()
            branch = args[0]

        if self._repoSection["name"] not in self.records:
            self.records[self._repoSection["name"]] = {}

        self.records[self._repoSection["name"]][name] = {
            "name": name.strip(), "alias": alias.strip(), "branch": branch.strip(),
            "config": self._repoSection["config"]
        }

    def fetch(self):
        return self._fetch_source(self._arguments.source, self._arguments.sourceType)

    def _fetch_source(self, source, source_type):
        data = []
        if source_type == "url":
            request = urllib2.Request(source)

            if self._arguments.username:
                base64string = base64.encodestring('%s:%s' % (self._arguments.username, self._arguments.password))[:-1]
                request.add_header("Authorization", "Basic %s" % base64string)

            try:
                data = urllib2.urlopen(request)
            except urllib2.HTTPError:
                print "error: Source list not found: (%s)!!!" % source
                exit()

            base_path = source[0:source.rindex("/")] + "/"
        else:
            try:
                data = open(source)
            except IOError:
                print "error: Could not open source list: (%s)!!!" % source
                exit()

            base_path = os.path.dirname(source)

        for line in data:
            line = line.strip()
            if line and not line.startswith("#"):
                if line.startswith("[") and line.endswith("]"):
                    self._process_section(line[1:-1].strip())
                elif line.startswith("<") and line.endswith(">"):
                    self._process_operation(line[1:-1].strip(), base_path)
                else:
                    self._process_line(line)

        return self.records


class Arguments:
    _sourcesUrlPrefix = SOURCE_URL_PREFIX

    username = None
    requirePassword = False
    passwordString = None
    password = None
    command = None
    path = None
    source = "oxwall"
    email = None
    verbose = False
    clearChanges = False
    disableChmod = False

    runDir = None

    sourceType = "url"

    def __init__(self, commands):
        self._commands = dict(zip(map(lambda c: c.name, commands), commands))
        self.source = "%s/%s" % (self._sourcesUrlPrefix, "oxwall")
        self.runDir = os.getcwd()

    def parse(self):
        self.parse_args()

    def parse_args(self):
        parser = argparse.ArgumentParser()

        parser.add_argument("command",
                            choices=self._commands.keys())

        parser.add_argument("source",
                            nargs='?',
                            type=self._source,
                            default=self.source,
                            help="Source list file. Might be url, path or a reserved name ( oxwall, skadate, etc.. )")

        parser.add_argument("path",
                            nargs='?',
                            default=".",
                            type=self._path,
                            help="Path to Oxwall Core root folder")

        parser.add_argument('-u', '--user',
                            dest="username",
                            required=False,
                            help="github.com user name")

        parser.add_argument('-e', '--email',
                            dest="email",
                            required=False,
                            help="github.com user email. Required for migrate command only")

        parser.add_argument('-p', '--prompt',
                            dest="requirePassword",
                            action="store_true",
                            default=self.requirePassword,
                            required=False,
                            help="Pass this flag if password authorization is required")

        parser.add_argument('--password',
                            dest="passwordString",
                            default=self.passwordString,
                            required=False,
                            help="Password string")

        parser.add_argument('-v', '--verbose',
                            dest="verbose",
                            action="store_true",
                            default=self.verbose,
                            required=False,
                            help="Pass this flag if you want more verbose output")

        parser.add_argument('-c', '--clear-changes',
                            dest="clearChanges",
                            action="store_true",
                            default=self.clearChanges,
                            required=False,
                            help="Pass this flag if you want to clear all changes you made. Cannot be undone!!!")

        parser.add_argument('--disable-chmod',
                            dest="disableChmod",
                            action="store_true",
                            default=self.disableChmod,
                            required=False,
                            help="Pass this flag if you want to disable chmod!!!")

        parser.parse_args(namespace=self)

    def _path(self, path):
        command = self._commands[self.command]

        return command.validate_path(path.rstrip(os.sep), self)

    def _source(self, source):
        if self.passwordString:
            self.password = self.passwordString
        else:
            if self.requirePassword and self.username:
                try:
                    self.password = getpass.getpass("Enter password for user '%s': " % self.username)
                except KeyboardInterrupt:
                    sys.exit(0)

        if _is_file(source):
            if not os.path.isfile(source):
                raise argparse.ArgumentTypeError('Source list not found')

            self.sourceType = "file"

            return os.path.abspath(source)

        self.sourceType = "url"

        if not _is_absolute_url(source):
            source = "%s/%s" % (self._sourcesUrlPrefix, source)

        try:
            request = urllib2.Request(source)

            if self.username:
                base64string = base64.encodestring('%s:%s' % (self.username, self.password))[:-1]
                request.add_header("Authorization", "Basic %s" % base64string)

            request.get_method = lambda: 'HEAD'
            urllib2.urlopen(request)
        except:
            raise argparse.ArgumentTypeError('Source list not found')

        return source

    def read_config(self, name):
        root_path = self.path if self.path else '.'
        path = os.path.join(root_path, ".owr", name)

        data = None
        if os.path.isfile(path):
            with open(path, "r") as f:
                data = f.read()

        return data

    def read_configs(self):
        username = self.read_config("username")
        if not (username is None):
            self.username = username

        email = self.read_config("email")
        if not (email is None):
            self.email = email

        require_password = self.read_config("require-password")
        if not (require_password is None):
            self.requirePassword = require_password

        source = self.read_config("source")
        if not (source is None):
            self.source = source

    def save_config(self, name, value):
        if not os.path.isdir(self.path):
            return

        owr_dir = os.path.join(self.path, ".owr")
        if not os.path.isdir(owr_dir):
            os.mkdir(owr_dir)

        path = os.path.join(owr_dir, name)
        with open(path, "w+") as f:
            f.write(str(value))

    def save_configs(self):
        self.save_config("username", self.username if self.username else "")
        self.save_config("require-password", 1 if self.requirePassword else 0)
        self.save_config("source", self.source if self.source else "")
        self.save_config("email", self.email if self.email else "")


class Command:
    composer_tmp_path = ''

    def __init__(self, name):
        self.name = name

    def validate_path(self, path, args):
        return path

    def fetched(self, sections, args):
        pass

    def main(self, root_dir, url, args, branch):
        pass

    def item(self, path, url, args, branch, *opt):
        pass

    def composer(self, path):
        if self.name not in ['update', 'clone'] or not os.path.exists('%s/composer.json' % path):
            return None

        if not self.composer_tmp_path:
            composer = urllib2.urlopen(COMPOSER_DOWNLOAD_URL)
            self.composer_tmp_path = tempfile.mkstemp()[1]
            output = open(self.composer_tmp_path, 'wb')
            output.write(composer.read())
            output.close()

        shutil.copyfile(self.composer_tmp_path, "%s/composer.phar" % path)
        if os.path.exists('%s/composer.lock' % path):
            sp = subprocess.Popen('php composer.phar update', shell=True, stdout=subprocess.PIPE, cwd=path)
        else:
            sp = subprocess.Popen('php composer.phar install', shell=True, stdout=subprocess.PIPE, cwd=path)
        result = sp.communicate()[0]
        print(result)

    def clear_temp(self):
        if self.name in ['update', 'clone']:
            os.remove(self.composer_tmp_path)

    def completed(self, root_dir, url, args):
        pass


class UpdateCommand(Command):
    def __init__(self):
        Command.__init__(self, "update")

    def validate_path(self, path, args):
        if not os.path.isdir(os.path.join(path, ".git")):
            raise argparse.ArgumentTypeError('Not a git repository')

        return path

    def main(self, root_dir, url, args, branch):
        quiet = ""
        if not args.verbose:
            _log_operation("update", url, root_dir, branch)
            quiet = "--quiet"

        abs_path = os.path.abspath(root_dir)
        os.system(("git --work-tree=%s --git-dir=%s pull " + quiet + " origin master") % (
            abs_path + os.sep, os.path.join(abs_path, ".git"))
        )

        if args.clearChanges:
            os.system(("git --work-tree=%s --git-dir=%s checkout " + quiet + " -- .") % (
                abs_path + os.sep, os.path.join(abs_path, ".git"))
            )

        if branch != "master":
            _change_branch(abs_path, branch, not args.verbose)

    def item(self, path, url, args, branch, create=True, *opt):
        quiet = ""
        if not args.verbose:
            quiet = "--quiet"

        if os.path.isdir(path):
            if not args.verbose:
                _log_operation("update", url, path, branch)

            if args.clearChanges:
                os.system(("git --work-tree=%s --git-dir=%s checkout " + quiet + " -- .") % (
                    path + os.sep, os.path.join(path, ".git"))
                )

            # Checkout master branch
            os.system(("git --work-tree=%s --git-dir=%s checkout " + quiet + " master") % (
                path + os.sep, os.path.join(path, ".git"))
            )

            # Pull master branch
            os.system(("git --work-tree=%s --git-dir=%s pull " + quiet + " origin master") % (
                path + os.sep, os.path.join(path, ".git"))
            )
        elif create:
            if not args.verbose:
                _log_operation("clone", url, path, branch)

            os.system("git clone " + quiet + " %s %s" % (url, path))

        if branch != "master":
            _change_branch(path, branch, not args.verbose)


class CloneCommand(Command):
    def __init__(self):
        Command.__init__(self, "clone")

    def validate_path(self, path, args):
        shall = True
        if os.path.isdir(path) and os.listdir(path):
            shall = raw_input("%s (Y/n): " % "Destination folder is not empty. Do you want to continue?").lower() == 'y'

        if not shall:
            sys.exit(0)

        if os.path.isdir(path) and os.path.isdir(os.path.join(path, ".git")):
            raise argparse.ArgumentTypeError('Destination folder should not contain git repository')

        return path

    def main(self, root_dir, url, args, branch):
        quiet = ""
        if not args.verbose:
            _log_operation("clone", url, root_dir, branch)
            quiet = "--quiet"

        if os.path.isdir(root_dir):

            tmp_dir = tempfile.mkdtemp()

            os.system(("git clone " + quiet + " --no-checkout %s %s") % (url, tmp_dir))
            shutil.move(os.path.join(tmp_dir, ".git"), os.path.join(root_dir, ".git"))
            os.chdir(root_dir)
            os.system("git reset " + quiet + " --hard HEAD")

            shutil.rmtree(tmp_dir)
        else:
            os.system("git clone " + quiet + " %s %s" % (url, root_dir))

        if branch != "master":
            _change_branch(root_dir, branch, not args.verbose)

        os.chdir(args.runDir)

    def item(self, path, url, args, branch, *opt):
        quiet = ""
        if not args.verbose:
            _log_operation("clone", url, path, branch)
            quiet = "--quiet"

        os.system("git clone " + quiet + " %s %s" % (url, path))

        if branch != "master":
            _change_branch(path, branch, not args.verbose)

    def completed(self, root_dir, url, args):
        config_file = os.path.join(root_dir, "ow_includes", "config.php")
        shutil.copyfile(os.path.join(root_dir, "ow_includes", "config.php.default"), config_file)

        templatec_path = os.path.join(root_dir, "ow_smarty", "template_c")
        if not os.path.isdir(templatec_path):
            os.mkdir(templatec_path)

        if not args.disableChmod:
            os.system("chmod 777 %s" % config_file)
            os.system("chmod -R 777 %s" % os.path.join(root_dir, "ow_userfiles"))
            os.system("chmod -R 777 %s" % os.path.join(root_dir, "ow_pluginfiles"))
            os.system("chmod -R 777 %s" % os.path.join(root_dir, "ow_static"))
            os.system("chmod -R 777 %s" % os.path.join(root_dir, "ow_log"))
            os.system("chmod -R 777 %s" % templatec_path)


class MigrateCommand(Command):
    def __init__(self):
        Command.__init__(self, "migrate")

    def validate_path(self, path, args):
        if not os.path.isfile(os.path.join(path, "ow_version.xml")):
            raise argparse.ArgumentTypeError('Oxwall based software not found')

        return path

    def main(self, root_dir, url, args, branch):
        if not args.username:
            print "error: Github user name is required !!!"
            exit()

        if not args.email:
            print "error: Github user email is required !!!"
            exit()

    def item(self, path, url, args, *opt):
        if not os.path.isdir(path):
            return

        tmp_dir = tempfile.mkdtemp()

        os.chdir(tmp_dir)

        os.system("git clone %s %s" % (url, tmp_dir))
        os.system("git config user.email %s" % args.email)
        os.system("git config user.name %s" % args.username)

        os.system("cp -r %s %s" % (os.path.join(path, "*"), tmp_dir + os.sep))

        os.system("git add .")
        os.system('git ci -m "Source code"')
        os.system("git push -u origin master")

        os.chdir(args.runDir)
        os.system("rm -rf %s" % tmp_dir)


# not completed
class InfoCommand(Command):
    def __init__(self):
        Command.__init__(self, "info")
        self.records = []

    def validate_path(self, path, args):
        if not os.path.isdir(os.path.join(path, ".owr")):
            raise argparse.ArgumentTypeError('owr information not found')

        return path

    def fetched(self, sections, args):
        pass

    def completed(self, root_dir, url, args):
        pass


class Builder:
    _arguments = None
    _parser = None

    _commands = {}

    _sectionFolders = {
        "plugins": "ow_plugins",
        "themes": "ow_themes"
    }

    def __init__(self, arguments, commands):
        self._parser = SourceListParser(arguments)
        self._arguments = arguments
        self._commands = dict(zip(map(lambda c: c.name, commands), commands))

    def process(self):
        command = self._commands[self._arguments.command]

        sections = self._parser.fetch()
        command.fetched(sections, self._arguments)

        auth_prefix = ""
        if self._arguments.username:
            auth = self._arguments.username
            if self._arguments.password:
                auth = "%s:%s" % (self._arguments.username, urllib2.quote(self._arguments.password))
            auth_prefix = "%s@" % auth

        # core
        try:
            core_record = sections["core"].values()[0]
            del sections["core"]
            core_branch = core_record["branch"]
            core_url = "https://%s%s/%s.git" % (auth_prefix, core_record["config"][0], core_record["name"])
        except KeyError:
            core_branch = "master"
            core_url = "https://github.com/oxwall/oxwall.git"

        command.main(os.path.abspath(self._arguments.path), core_url, self._arguments, core_branch)
        command.composer(os.path.abspath(self._arguments.path))

        # install
        try:
            install_record = sections["install"].values()[0]
            del sections["install"]
            install_branch = install_record["branch"]
            install_url = "https://%s%s/%s.git" % (auth_prefix, install_record["config"][0], install_record["name"])
        except KeyError:
            install_branch = "master"
            install_url = "https://github.com/oxwall/install.git"

        command.item(os.path.abspath(os.path.join(self._arguments.path, "ow_install")), install_url, self._arguments,
                     install_branch, False)

        for sectionName in sections:
            records = sections[sectionName]

            try:
                dir_name = self._sectionFolders[sectionName]
            except IndexError:
                continue

            for name in records:
                record = records[name]
                path = os.path.abspath(os.path.join(self._arguments.path, dir_name, record["alias"]))
                repo_prefix = record["config"][0]  # repository prefix
                url = "https://%s%s/%s.git" % (auth_prefix, repo_prefix, record["name"])
                command.item(path, url, self._arguments, record["branch"])
                command.composer(path)

        command.clear_temp()
        command.completed(self._arguments.path, core_url, self._arguments)


def main():
    commands = [CloneCommand(), UpdateCommand(), MigrateCommand()]
    arguments = Arguments(commands)

    arguments.read_configs()
    arguments.parse()

    builder = Builder(arguments, commands)
    builder.process()

    arguments.save_configs()

    print "\n%s command was completed !!!" % arguments.command


if __name__ == "__main__":
    main()
