#!/usr/bin/env python

import argparse
import os, sys, shutil
import urllib2, base64
import getpass
import tempfile
import re

SOURCE_URL_PREFIX = "https://raw.githubusercontent.com/skalfa/scripts/master/owr/sources"

def _is_file(filePath):
    return filePath.startswith((".", "..", os.sep, "~"))

def _is_relative_path(filePath):
    return filePath.startswith((".", ".."))

def _is_relative_url(url):
    return not _is_absolute_url(url) and "/" in url

def _is_absolute_url(url):
    return url.startswith(("http://", "https://"))

def _change_branch(dir, branch, isQuiet = True):
    quiet = "--quiet" if isQuiet else ""
    os.system(("git --work-tree=%s --git-dir=%s fetch " + quiet + " origin %s") % (dir + os.sep, os.path.join(dir, ".git"), branch))
    os.system(("git --work-tree=%s --git-dir=%s checkout " + quiet + " origin/%s") % (dir + os.sep, os.path.join(dir, ".git"), branch))

def _log_operation(operation, repoUrl, path, branch):
    class Colors:
        BLUE = '\033[94m'
        RED = '\033[91m'
        END = '\033[0m'

    repoName = repoUrl[repoUrl.rindex("/") + 1:-4]
    branchColor = Colors.BLUE if branch == "master" else Colors.RED

    args = (Colors.BLUE + repoName + Colors.END, branchColor + branch + Colors.END, Colors.BLUE + path + Colors.END)

    if operation == "update":
        print ("Updating %s (%s) in %s") % args
    elif operation == "clone":
        print ("Cloning %s (%s) to %s") % args


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

    def _processOperation(self, command, basePath):
        parts = map(str.strip, command.split(" "))

        gSourceType = self._arguments.sourceType

        def include(source, *args):
            if gSourceType == "file" and _is_file(source):
                path = source
                if _is_relative_path(source):
                    path = os.path.normpath(os.path.join(basePath, source))

                return self._fetchSource(path, "file")

            url = source if _is_absolute_url(source) else "%s/%s" % (SOURCE_URL_PREFIX, source)

            return self._fetchSource(url, "url")

        operations = {"include": include}

        try:
            operation = operations[parts[0]]
            args = parts[1:]
            operation(*args)
        except (IndexError, KeyError, TypeError):
            return


    def _processSection(self, section, basePath):
        parts = map(str.strip, section.split(" "))
        self._repoSection["name"] = parts[0]
        self._repoSection["config"] = parts[1:] if len(parts) > 1 else self._defaultConfig

    def _processLine(self, line, basePath):
        parts = map(str.strip, line.split("="))

        name = parts[0]
        try:
            alias = parts[1]
        except IndexError:
            alias = name

        branch = "master"
        regExp = re.compile("\((.*)\)")
        args = re.findall(regExp, alias)

        if args:
            alias = re.sub(regExp, "", alias)
            name = re.sub(regExp, "", name)
            branch = args[0]

        if not self.records.has_key(self._repoSection["name"]):
            self.records[self._repoSection["name"]] = {}

        self.records[self._repoSection["name"]][name] = {
            "name": name.strip(), "alias": alias.strip(), "branch": branch.strip(), "config": self._repoSection["config"]
        }

    def fetch(self):
        return self._fetchSource(self._arguments.source, self._arguments.sourceType)

    def _fetchSource(self, source, sourceType):
        data = []
        if sourceType == "url":
            request = urllib2.Request(source)

            if self._arguments.username:
                base64string = base64.encodestring('%s:%s' % (self._arguments.username, self._arguments.password))[:-1]
                request.add_header("Authorization", "Basic %s" % base64string)

            try:
                data = urllib2.urlopen(request)
            except urllib2.HTTPError:
                pass

            basePath = source[0:source.rindex("/")] + "/"
        else:
            try:
                data = open(source)
            except IOError:
                pass

            basePath = os.path.dirname(source)

        for line in data:
            line = line.strip()
            if line and not line.startswith("#"):
                if line.startswith("[") and line.endswith("]"):
                    self._processSection(line[1:-1].strip(), basePath)
                elif line.startswith("<") and line.endswith(">"):
                    self._processOperation(line[1:-1].strip(), basePath)
                else:
                    self._processLine(line, basePath)

        return self.records

class Arguments:

    _sourcesUrlPrefix = SOURCE_URL_PREFIX

    username = None
    requirePassword = False
    password = None
    command = None
    path = None
    source = "oxwall"
    email = None
    verbose = False

    runDir = None


    sourceType="url"

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
                            type=self._Source,
                            default=self.source,
                            help="Source list file. Might be url, path or a reserved name ( oxwall, skadate, etc.. )")

        parser.add_argument("path",
                            nargs='?',
                            default=".",
                            type=self._Path,
                            help="Path to Oxwall Core root folder")

        parser.add_argument('-u','--user',
                            dest="username",
                            required=False,
                            help="github.com user name")

        parser.add_argument('-e','--email',
                            dest="email",
                            required=False,
                            help="github.com user email. Required for migrate command only")

        parser.add_argument('-p','--password',
                            dest="requirePassword",
                            action="store_true",
                            default=self.requirePassword,
                            required=False,
                            help="Pass this flag if password authorization is required")

        parser.add_argument('-v','--verbose',
                            dest="verbose",
                            action="store_true",
                            default=self.verbose,
                            required=False,
                            help="Pass this flag if you want more verbose output")

        parser.parse_args(namespace=self)

    def _Path(self, path):
        command = self._commands[self.command]

        return command.validatePath(path.rstrip(os.sep), self)

    def _Source(self, source):
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
            raise argparse.ArgumentTypeError( 'Source list not found' )

        return source

    def readConfig(self, name):
        rootPath = self.path if self.path else '.'
        path = os.path.join(rootPath, ".owr", name)

        data = None
        if os.path.isfile(path):
            with open (path, "r") as file:
                data=file.read()

        return data

    def readConfigs(self):
        username = self.readConfig("username")
        if not (username is None):
            self.username = username

        email = self.readConfig("email")
        if not (email is None):
            self.email = email

        requirePassword = self.readConfig("require-password")
        if not (requirePassword is None):
            self.requirePassword = requirePassword

        source = self.readConfig("source")
        if not (source is None):
            self.source = source

    def saveConfig(self, name, value):
        if not os.path.isdir(self.path):
            return

        owrDir=os.path.join(self.path, ".owr")
        if not os.path.isdir(owrDir):
            os.mkdir(owrDir)

        path = os.path.join(owrDir, name)
        with open(path, "w+") as file:
            file.write(str(value))


    def saveConfigs(self):
        self.saveConfig("username", self.username if self.username else "")
        self.saveConfig("require-password", 1 if self.requirePassword else 0)
        self.saveConfig("source", self.source if self.source else "")
        self.saveConfig("email", self.email if self.email else "")


class Command:

    def __init__(self, name):
        self.name = name

    def validatePath(self, path, args):
        return path

    def fetched(self, sections, args):
        pass

    def main(self, rootDir, url, args, branch):
        pass

    def item(self, path, url, args, branch, *opt):
        pass

    def completed(self, rootDir, url, args):
        pass

class UpdateCommand(Command):
    def __init__(self):
        Command.__init__(self, "update")

    def validatePath(self, path, args):
        if not os.path.isdir(os.path.join(path, ".git")):
            raise argparse.ArgumentTypeError('Not a git repository')

        return path

    def main(self, rootDir, url, args, branch):
        quiet = ""
        if not args.verbose:
            _log_operation("update", url, rootDir, branch)
            quiet = "--quiet"

        absPath = os.path.abspath(rootDir)
        os.system(("git --work-tree=%s --git-dir=%s pull " + quiet + " origin master") % (absPath + os.sep, os.path.join(absPath, ".git")))

        if branch != "master":
            _change_branch(absPath, branch, not args.verbose)

    def item(self, path, url, args, branch, create = True, *opt):
        quiet = ""
        if not args.verbose:
            quiet = "--quiet"

        if os.path.isdir(path):
            if not args.verbose:
                _log_operation("update", url, path, branch)

            # Checkout master branch
            os.system(("git --work-tree=%s --git-dir=%s checkout " + quiet + " master") % (path + os.sep, os.path.join(path, ".git")))

            # Pull master branch
            os.system(("git --work-tree=%s --git-dir=%s pull " + quiet + " origin master") % (path + os.sep, os.path.join(path, ".git")))
        elif create:
            if not args.verbose:
                _log_operation("clone", url, path, branch)

            os.system("git clone " + quiet + " %s %s" % (url, path))

        if branch != "master":
            _change_branch(path, branch, not args.verbose)

class CloneCommand(Command):
    def __init__(self):
        Command.__init__(self, "clone")

    def validatePath(self, path, args):
        shall = True
        if os.path.isdir(path) and os.listdir(path):
            shall = raw_input("%s (Y/n): " % "Destination folder is not empty. Do you want to continue?").lower() == 'y'

        if not shall:
            sys.exit(0)

        if os.path.isdir(path) and os.path.isdir(os.path.join(path, ".git")):
            raise argparse.ArgumentTypeError('Destination folder should not contain git repository')

        return path

    def main(self, rootDir, url, args, branch):
        quiet = ""
        if not args.verbose:
            _log_operation("clone", url, rootDir, branch)
            quiet = "--quiet"

        if os.path.isdir(rootDir):

            tmpDir = tempfile.mkdtemp()

            os.system(("git clone " + quiet + " --no-checkout %s %s") % (url, tmpDir))
            shutil.move(os.path.join(tmpDir, ".git"), os.path.join(rootDir, ".git"))
            os.chdir(rootDir)
            os.system("git reset " + quiet + " --hard HEAD")

            shutil.rmtree(tmpDir)
        else:
            os.system("git clone " + quiet + " %s %s" % (url, rootDir))

        if branch != "master":
            _change_branch(rootDir, branch, not args.verbose)

        os.chdir(args.runDir)

    def item(self, path, url, args, branch, *opt):
        quiet = ""
        if not args.verbose:
            _log_operation("clone", url, path, branch)
            quiet = "--quiet"

        os.system("git clone " + quiet + " %s %s" % (url, path))

        if branch != "master":
            _change_branch(path, branch, not args.verbose)

    def completed(self, rootDir, url, args):
        configFile = os.path.join(rootDir, "ow_includes", "config.php")
        shutil.copyfile(os.path.join(rootDir, "ow_includes", "config.php.default"), configFile)

        os.system("chmod 777 %s" % configFile)
        os.system("chmod -R 777 %s" % os.path.join(rootDir, "ow_userfiles"))
        os.system("chmod -R 777 %s" % os.path.join(rootDir, "ow_pluginfiles"))
        os.system("chmod -R 777 %s" % os.path.join(rootDir, "ow_static"))
        os.system("chmod -R 777 %s" % os.path.join(rootDir, "ow_log"))

        templatecPath = os.path.join(rootDir, "ow_smarty", "template_c")
        if not os.path.isdir(templatecPath):
            os.mkdir(templatecPath)

        os.system("chmod -R 777 %s" % templatecPath)


class MigrateCommand(Command):
    def __init__(self):
        Command.__init__(self, "migrate")

    def validatePath(self, path, args):
        if not os.path.isfile(os.path.join(path, "ow_version.xml")):
            raise argparse.ArgumentTypeError('Oxwall based software not found')

        return path

    def main(self, rootDir, url, args):
        if not args.username:
            print "error: Github user name is required !!!"
            exit()

        if not args.email:
            print "error: Github user email is required !!!"
            exit()

    def item(self, path, url, args, *opt):
        if not os.path.isdir(path):
            return

        tmpDir = tempfile.mkdtemp()

        os.chdir(tmpDir)

        os.system("git clone %s %s" % (url, tmpDir))
        os.system("git config user.email %s" % args.email)
        os.system("git config user.name %s" % args.username)

        os.system("cp -r %s %s" % (os.path.join(path, "*"), tmpDir + os.sep))

        os.system("git add .")
        os.system('git ci -m "Source code"')
        os.system("git push -u origin master")

        os.chdir(args.runDir)
        os.system("rm -rf %s" % tmpDir)

# not completed
class InfoCommand(Command):
    def __init__(self):
        Command.__init__(self, "info")
        self.records = []

    def validatePath(self, path, args):
        if not os.path.isdir(os.path.join(path, ".owr")):
            raise argparse.ArgumentTypeError('owr information not found')

        return path

    def fetched(self, sections, args):
        pass

    def completed(self, rootDir, url, args):
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

        authPrefix = ""
        if self._arguments.username:
            auth = self._arguments.username
            if self._arguments.password:
                auth = "%s:%s" % (self._arguments.username, urllib2.quote(self._arguments.password))
            authPrefix = "%s@" % auth

        # core
        try:
            coreRecord = sections["core"].values()[0]
            del sections["core"]
            coreUrl = "https://%s%s/%s.git" % (authPrefix, coreRecord["config"][0], coreRecord["name"])
        except KeyError:
            coreUrl = "https://github.com/oxwall/oxwall.git"

        command.main(os.path.abspath(self._arguments.path), coreUrl, self._arguments, coreRecord["branch"])

        # install
        try:
            installRecord = sections["install"].values()[0]
            del sections["install"]
            installUrl = "https://%s%s/%s.git" % (authPrefix, installRecord["config"][0], installRecord["name"])
        except KeyError:
            installUrl = "https://github.com/oxwall/install.git"


        command.item(os.path.abspath(os.path.join(self._arguments.path, "ow_install")), installUrl, self._arguments, installRecord["branch"], False)

        for sectionName in sections:
            records = sections[sectionName]

            try:
                dirName = self._sectionFolders[sectionName]
            except IndexError:
                continue

            for name in records:
                record = records[name]
                path = os.path.abspath(os.path.join(self._arguments.path, dirName, record["alias"]))
                repoPrefix = record["config"][0] # repository prefix
                url = "https://%s%s/%s.git" % (authPrefix, repoPrefix, record["name"])
                command.item(path, url, self._arguments, record["branch"])

        command.completed(self._arguments.path, coreUrl, self._arguments)

def main():
    commands = [CloneCommand(), UpdateCommand(), MigrateCommand()]
    arguments = Arguments(commands)

    arguments.readConfigs()
    arguments.parse()

    builder = Builder(arguments, commands)
    builder.process()

    arguments.saveConfigs()

    print "\n%s command was completed !!!" % arguments.command

if __name__ == "__main__":
    main()