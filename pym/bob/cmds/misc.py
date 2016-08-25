# Bob build tool
# Copyright (C) 2016  TechniSat Digital GmbH
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from ..input import RecipeSet
import argparse
import sys

def doLS(argv, bobRoot):
    def showTree(packages, showAll, prefix=""):
        i = 0
        for p in packages:
            last = (i >= len(packages)-1)
            print("{}{}{}".format(prefix, "└── " if last else "├── ", p.getName()))
            deps = p.getAllDepSteps() if showAll else p.getDirectDepSteps()
            showTree([d.getPackage() for d in deps], showAll,
                     prefix + ("    " if last else "│   "))
            i += 1

    def showPrefixed(packages, recurse, showAll, stack, level=0):
        for p in packages:
            newStack = stack[:]
            newStack.append(p.getName())
            print("/".join(newStack))
            if recurse:
                deps = p.getAllDepSteps() if showAll else p.getDirectDepSteps()
                showPrefixed([d.getPackage() for d in deps], recurse, showAll,
                             newStack, level+1)

    parser = argparse.ArgumentParser(prog="bob ls", description='List packages.')
    parser.add_argument('package', type=str, nargs='?',
                        help="Sub-package to start listing from")
    parser.add_argument('-a', '--all', default=False, action='store_true',
                        help="Show indirect dependencies too")
    parser.add_argument('-r', '--recursive', default=False, action='store_true',
                        help="Recursively display dependencies")
    parser.add_argument('-p', '--prefixed', default=False, action='store_true',
                        help="Prints the full path prefix for each package")
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--sandbox', action='store_true', default=True,
        help="Enable sandboxing")
    group.add_argument('--no-sandbox', action='store_false', dest='sandbox',
        help="Disable sandboxing")
    args = parser.parse_args(argv)

    recipes = RecipeSet()
    recipes.parse()

    showAll = args.all
    roots = sorted(recipes.generatePackages(lambda s,m: "unused", sandboxEnabled=args.sandbox).values(), key=lambda a:a.getName())
    stack = []
    if args.package:
        steps = [ s for s in args.package.split("/") if s != "" ]
        for s in steps:
            roots = [ r for r in roots if r.getName() == s ]
            if not roots:
                print("{}: not found in '{}'".format(s, "/".join(stack)),
                      file=sys.stderr)
                sys.exit(1)
            if showAll:
                roots = [ d.getPackage() for d in roots[0].getAllDepSteps() ]
            else:
                roots = [ d.getPackage() for d in roots[0].getDirectDepSteps() ]
            stack.append(s)
    else:
        steps = ["/"]

    if args.prefixed:
        showPrefixed(roots, args.recursive, showAll, stack)
    elif args.recursive:
        print("/".join(steps))
        showTree(roots, showAll)
    else:
        for p in roots: print(p.getName())

def doQuerySCM(argv, bobRoot):
    # Recursive query function
    def queryRecursive(packages, prefix, printer, match):
        for p in packages:
            name = p.getName()
            for scm in p.getCheckoutStep().getScmList():
                if len(match) == 0:
                    urls = scm.getUrls()
                else:
                    urls = scm.matchUrls(match)
                for url in urls:
                    printer(prefix+name, url)
            queryRecursive([d.getPackage() for d in p.getAllDepSteps()], prefix + name + "/", printer, match)

    # Configure the parser
    parser = argparse.ArgumentParser(prog="bob query-scm", description='Lists all packages and their SCM URLs.')
    parser.add_argument('--show', help='Select output format (both, name/package, url)', default='both', metavar='MODE')
    parser.add_argument('-f', '--filter', help='Show only packages that match a SCM URL', action='append', metavar='URL', default=[])

    group = parser.add_mutually_exclusive_group()
    group.add_argument('--sandbox', action='store_true', default=True,
        help="Enable sandboxing")
    group.add_argument('--no-sandbox', action='store_false', dest='sandbox',
        help="Disable sandboxing")

    args = parser.parse_args(argv)

    # Select a printer mode:
    def printBoth(name, url): print(name+"\t"+url)
    def printName(name, url): print(name)
    def printUrl(name, url): print(url)
    if args.show == 'both':
        printer = printBoth
    elif args.show == 'name' or args.show == 'package':
        printer = printName
    elif args.show == 'url':
        printer = printUrl
    else:
        print("Unknown output format '{}'.".format(args.show), file=sys.stderr)
        exit(1)

    # Do it
    recipes = RecipeSet()
    recipes.parse()
    roots = recipes.generatePackages(lambda s,m: "unused", sandboxEnabled=args.sandbox).values()
    queryRecursive(roots, "", printer, args.filter)

def doQueryPath(argv, bobRoot):
    # Local imports
    from .build import LocalBuilder
    from ..state import BobState
    from ..utils import asHexStr
    from ..input import walkPackagePath

    # Configure the parser
    parser = argparse.ArgumentParser(prog="bob query-path",
                                     description="Lists all packages and their last build directory. If a package has never been built, no output is shown for that package.")
    parser.add_argument('packages', metavar='PACKAGE', type=str, nargs='+',
        help="(Sub-)package to build")
    parser.add_argument('--show', help='Select output format (both, name/package, path)', default='both', metavar='MODE')
    parser.add_argument('-D', default=[], action='append', dest="defines",
        help="Override default environment variable")
    parser.add_argument('-c', dest="configFile", default=[], action='append',
        help="Use config File")

    group = parser.add_mutually_exclusive_group()
    group.add_argument('--sandbox', action='store_true', default=True,
        help="Enable sandboxing")
    group.add_argument('--no-sandbox', action='store_false', dest='sandbox',
        help="Disable sandboxing")

    # Parse args
    args = parser.parse_args(argv)

    # Select a printer mode
    def printBoth(name, path): print(name+"\t"+path)
    def printName(name, path): print(name)
    def printPath(name, path): print(path)
    if args.show == 'both':
        printer = printBoth
    elif args.show == 'name' or args.show == 'package':
        printer = printName
    elif args.show == 'path':
        printer = printPath
    else:
        print("Unknown output format '{}'.".format(args.show), file=sys.stderr)
        exit(1)

    # Process defines
    defines = {}
    for define in args.defines:
        d = define.split("=")
        if len(d) == 1:
            defines[d[0]] = ""
        elif len(d) == 2:
            defines[d[0]] = d[1]
        else:
            parser.error("Malformed define: "+define)

    # Process the recipes
    recipes = RecipeSet()
    recipes.defineHook('developNameFormatter', LocalBuilder.developNameFormatter)
    recipes.parse()

    # Find the name formatter -- do we need it?
    nameFormatter = recipes.getHook('developNameFormatter')
    nameFormatter = LocalBuilder.makeRunnable(nameFormatter)
    roots = recipes.generatePackages(nameFormatter, defines, args.sandbox)

    # Load state
    state = BobState()

    for p in args.packages:
        package = walkPackagePath(roots, p)
        dir = state.getByNameDirectoryMaybe(asHexStr(package.getPackageStep().getVariantId()))
        if dir != None:
            printer(p, dir)
