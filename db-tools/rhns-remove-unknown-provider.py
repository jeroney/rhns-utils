#!/usr/bin/python

###
#
# WARNING DO A BACKUP OF THE DB BEFORE USING THIS SCRIPT
# SHOULD ONLY BE USED WHEN ASKED TO BY SUPPORT
#
###
###
# To the extent possible under law, Red Hat, Inc. has dedicated all copyright to this software to the public domain worldwide, pursuant to the CC0 Public Domain Dedication. 
# This software is distributed without any warranty.  See <http://creativecommons.org/publicdomain/zero/1.0/>.
###

__author__ = "Felix Dewaleyne"
__credits__ = ["Felix Dewaleyne"]
__license__ = "GPL"
__version__ = "0.11.1c"
__maintainer__ = "Felix Dewaleyne"
__email__ = "fdewaley@redhat.com"
__status__ = "beta"

# This script exports a list of packages that would be removed by a specific query and then does the removal - after confirmation.
# On the next call it loads the list and tries to find the packages one by one in the satellite to clone them in the channels they were removed from
# best not used on other versions thatn 5.6 currently

import xmlrpclib

#connector class -used to initiate a connection to a satellite and to send the proper satellite the proper commands
class RHNSConnection:

    username = None
    host = None
    key = None
    client = None
    closed = False
    orgid = 1
    __channel_queues = {}

    def __init__(self, username, password, host):
        """connects to the satellite db with given parameters"""
        URL = "https://%s/rpc/api" % host
        self.client = xmlrpclib.Server(URL)
        self.key = self.client.auth.login(username, password)
        self.username = username
        self.__password = password
        self.host = host
        #store the orgid
        userdetails = self.client.user.getDetails(self.key, self.username)
        self.orgid = userdetails['org_id']
        pass

    def reconnect(self):
        """re-establishes the connection"""
        self.client = xmlrpclib.Server("https://%s/rpc/api" % self.host)
        self.key = self.client.auth.login(self.username, self.__password)
        pass

    def close(self):
        """closes a connection. item can be destroyed then"""
        self.client.auth.logout(self.key)
        self.closed = True
        pass

    def get_redhat_channels(self):
        """returns the list of red hat channels. if that has already been called, returns the same value as previously"""
        if not hasattr(self, 'rh_channels'):
            self.rh_channels = []
            for channel in self.client.channel.listRedHatChannels(self.key):
                self.rh_channels.append(channel["label"])
        return self.rh_channels

    def channel_exists(self,label):
        """checks if a channel exists. returns true or false and reuses previous results"""
        if not hasattr(self, 'channels'):
            self.channels = []
            for channel in self.client.channel.listAllChannels(self.key):
                self.channels.append(channel["label"])
        if label in self.channels:
            return True
        else:
            return False

    def queue_to_channel(self, pid, channel):
        """adds a package to the queue for that channel, if it isn't already queued"""
        if not channel in self.__channel_queues:
            self.__channel_queues[channel] = []
        if not pid in self.__channel_queues[channel]:
            self.__channel_queues[channel].append(pid)

    def __process(self, clabel):
        """processes one list of packages in one call to clabel, attempting two times"""
        try:
            self.client.channel.software.addPackages(self.key, clabel, self.__channel_queues[clabel])
        except:
            #try one more time on a new connection then raise or continue
            try:
                self.reconnect()
                self.client.channel.software.addPackages(self.key, clabel, self.__channel_queues[clabel])
            except:
                raise
            pass

    def process_queues(self,ppc = 100):
        """processes the queues one by one, 100 packages at a time (ppc setting) - if using 0, process each channel in one call.."""
        for cqueue in self.__channel_queues:
            print "running queue for %s" % (cqueue)
            if self.__channel_queues[cqueue] / ppc < 1:
                print "less than %d packages queued, running in one call to add all %d" % (ppc, len(self.__channel_queues[cqueue]))
                self.__process(self.__channel_queues[cqueue])
            elif ppc == 0:
                print "processing as is with %d packages queued" % (len(self.__channel_queues[cqueue]))
                self.__process(self.__channel_queues[cqueue])
            else:
                rqueue = self.__channel_queues[cqueue]
                queue = []
                pos = ppc
                print "%d of %d" % (0, len(self.__channel_queues[cqueue]))
                while len(rqueue) > 0:
                    #process the queue pcc elements a time
                    if len(rqueue) > ppc:
                        queue, rqueue = rqueue[:ppc], queue[ppc:]
                    else:
                        #rqueue is ppc or less long, store all into queue and leave nothing into rqueue
                        queue, rqueue = rqueue, []
                    print '\r'+"%d of %d" % (pos, len(self.__channel_queues[cqueue]))
                    self.__process(queue)
                    pos += ppc
                print ""
        pass

    def __exit__(self, type, value, tb):
        """closes connection on exit"""
        if not self.closed :
            self.client.auth.logout(self.key)
        pass

import pickle
#class used to handle the backup information
class PackagesInfo:

    packages = {}
    channels = []
    bkpfile = None

    def __init__(self,filename):
        """creates a new file or loads it, by default creates a new file. Uses pickle to store and load data."""
        import os.path
        if os.path.isfile(filename):
            self.bkpfile = open(filename, 'r+')
            self.loadbkp()
        else:
            self.bkpfile = open(filename, 'w+')

    def loadbkp(self):
        """loads packages from pickle"""
        self.packages = pickle.load(self.bkpfile)

    def save(self):
        """saves package list to file using pickle"""
        pickle.dump(self.packages, self.bkpfile)

    def list(self):
        """prints the contents of the package list currently loaded"""
        print "Content of the backup: "
        for package in self.packages:
            print "package %s in channels %s" % (_pkgname(self.packages[package]['packageinfo']), ', '.join(self.packages[package]['channels']))

    def add(self, package_id, channel, packageinfo):
        """adds a package and associated channel to the object"""
        global verbose
        if package_id in self.packages:
            if not channel in self.packages[package_id]['channels']:
                self.packages[package_id]['channels'].append(channel)
                if verbose:
                    print "%s found in %s" % (_pkgname(packageinfo), channel)
            elif verbose:
                print "%s already recorded as being in %s" % (_pkgname(packageinfo), channel)
        else:
            if channel is not None:
                self.packages[package_id] = {'channels': [channel], 'packageinfo': packageinfo}
                if verbose:
                    print "%s found in %s" % (_pkgname(packageinfo), channel)
            elif verbose:
                print "%s is a package that is in no channel - omitting from backup" % (_pkgname(packageinfo))

    def cleanup(self):
        """removes packages with empty channels from the packages dictionary"""
        global verbose
        to_remove = []
        for package in self.packages:
            if self.packages[package] == [None] or len(self.packages[package]) == 0:
                to_remove.append(package)
        for package in to_remove:
            del self.packages[package]
        if verbose:
            print "removed %d packages found having no channels from the backup" % (len(to_remove))

    def __exit__(self, type, value, tb):
        """closes file on exit"""
        if not self.bkpfile.closed:
            self.bkpfile.close()

#load the classes required to access the db, fails if they are not present
import sys
sys.path.append("/usr/share/rhn")
try:
    import spacewalk.common.rhnConfig as rhnConfig
    import spacewalk.server.rhnSQL as rhnSQL
except ImportError:
    try:
        import common.rhnConfig as rhnConfig
        import server.rhnSQL as rhnSQL
    except ImportError:
        print "Couldn't load the libraries required to connect to the db"
        sys.exit(1)

#db related functions
def db_backup(bkp):
    """captures the data from the db and stores it in the backup"""
    rhnSQL.initDB()
    # selects all packages that are from unknown providers
    query = """
    select  
        rp.id as "package_id", 
        rpn.name as "package_name",
        rpe.version as "package_version",
        rpe.release as "package_release",
        rpe.epoch as "package_epoch",
        rpa.label as "package_arch",
        rc.label as "channel_label",
        rc.id as "channel_id"
    from rhnpackage rp
        inner join rhnpackagename rpn on rpn.id = rp.name_id
        inner join rhnpackageevr rpe on rpe.id = rp.evr_id
        inner join rhnpackagearch rpa on rpa.id = rp.package_arch_id
        left outer join rhnchannelpackage rcp on rcp.package_id = rp.id
        left outer join rhnchannel rc on rc.id = rcp.channel_id
        left outer join rhnpackagekeyassociation rpka on rpka.package_id = rp.id
    where rpka.key_id is null
    order by 2, 3
    """
    cursor = rhnSQL.prepare(query)
    cursor.execute()
    rows = cursor.fetchall_dict()
    print "backing up the list of packages"
    if not rows is None:
        c = 0
        for row in rows:
            c += 1
            bkp.add(row['package_id'],row['channel_label'], {'name': row['package_name'], 'version': row['package_version'], 'release': row['package_release'], 'epoch': row['package_epoch'], 'arch': row['package_arch']})
            if not verbose:
                print "\r%s of %s" % (str(c), str(len(rows))),
        if not verbose:
            print ""
        else:
            print "%s entries treated" % (str(len(rows)))
    else:
        print "no packages to backup"
    rhnSQL.closeDB()

from distutils.util import strtobool
def ask(question):
    """asks a question and waits for y/n"""
    print '%s [y/n]\n' % (question)
    while True:
        try:
            return strtobool(raw_input().lower())
        except ValueError:
            sys.stdout.write('Use \'y\' or \'n\'\n')

def db_clean(bkp):
    db_backup(bkp)
    bkp.save()
    rhnSQL.initDB()
    # delete from rhnchannelpackage entries that have an unknown provider and are packages in a RH channel
    queryA = """
    delete from rhnchannelpackage where package_id in (
        select distinct rp.id as "pid"
        from rhnpackage rp  
            left outer join rhnchannelpackage rcp on rcp.package_id = rp.id  
            left outer join rhnchannel rc on rc.id = rcp.channel_id  
            left outer join rhnpackagekeyassociation rpka on rpka.package_id = rp.id  
            left outer join rhnpackagekey rpk on rpk.id = rpka.key_id  
        where rpka.key_id is null and rc.channel_product_id is not null
    )
    """
    # delete rhnpackage entries not in any channel
    queryB = """
    delete from rhnpackage where id in (
        select distinct rp.id as "pid"
        from rhnpackage rp
            left outer join rhnchannelpackage rcp on rcp.package_id = rp.id  
            left outer join rhnchannel rc on rc.id = rcp.channel_id  
        where rcp.channel_id is null
    )
    """

    answer = ask("Continue with the deletion of the entries?")
    if not answer :
        print "leaving..."
    else:
        answer = ask("Did you take a backup of your database?")
        if not answer:
            print "you need to take one to be able to roll back"
        else:
            try:
                cursor = rhnSQL.prepare(queryA)
                cursor.execute()
                cursor = rhnSQL.prepare(queryB)
                cursor.execute()
                rhnSQL.commit()
            except:
                rhnSQL.rollback()
                raise
            print "entries deleted"

def _pkgname(h):
    if h['epoch'] in [None, '']:
        return "%s-%s-%s.%s" % (h['name'], str(h['version']) ,str(h['release']), h.get('arch',h.get('arch_label')))
    else:
        return "%s:%s-%s-%s.%s" % (str(h['epoch']), h['name'], str(h['version']), str(h['release']), h.get('arch',h.get('arch_label')))

def _lucenestr(i):
    """returns a lucene search string depending on the values given"""
    #note : this section uses data from the backup only. no need to replace arch.
    if i['epoch'] is None:
        return "name:%s AND version:%s AND release:%s AND arch:%s" % (i['name'], i['version'], i['release'], i['arch'])
    else:
        return "name:%s AND version:%s AND release:%s AND arch:%s AND epoch:%s" % (i['name'], i['version'], i['release'], i['arch'], i['epoch'])


def _api_add(pid, channels, conn):
    """adds a package into all those channels"""
    global verbose
    try:
        pchannels = conn.client.packages.listProvidingChannels(conn.key, pid)
    except:
        try:
            conn.reconnect()
            pchannels = conn.client.packages.listProvidingChannels(conn.key, pid)
        except:
            raise
        pass
    lpchannels = []
    for pchannel in pchannels:
        lpchannels.append(pchannel['label'])
    for channel in channels:
        if channel not in conn.get_redhat_channels() and conn.channel_exists(channel):
            if channel in lpchannels:
                print "skipping : package %d already in %s" % (pid, channel)
            else:
                if verbose:
                    print "queueing package %d to %s" % (pid, channel)
                conn.queue_to_channel(pid,channel)
        elif verbose and conn.channel_exists(channel):
            print "skipping %s : Red Hat channel " % (channel)
        elif verbose:
            print "skipping %s : Does not exist in the satellite" % (channel)
    print "processing all queues"
    #todo : implement option to change the number of packge per request by passing the value to this call
    conn.process_queues()

            

def _cmp_pkginfo(a,b):
    """logic to compare packages with the output of lucene. required since lucene returns '' instead of None"""
    global verbose;
    if a['name'] == b['name'] and a['version'] == b['version'] and a['release'] == b['release'] and a.get('arch',a.get('arch_label')) == b.get('arch',b.get('arch_label')):
        if a['epoch'] in ['',None] and b['epoch'] in ['',None] :
            if verbose:
                print "package info matched, both packages have no epoch"
            return True
        elif a['epoch'] == b['epoch']:
            if verbose:
                print "package info matched, both packages have the same epoch"
            return True
        else:
            if verbose:
                print "packages do not match. reason:"
                #only epoch can be different in this part
                if a['epoch'] != b['epoch']:
                    if a['epoch'] in ['',None] and b['epoch'] in ['',None]:
                        print "epochs are different but set to empty values (exception in matches)"
                    else:
                        print "epochs are different, '%s' is different to '%s'" % (a['epoch'],b['epoch'])
            return False
    else:
        if verbose:
            print "packages do not match. reason:"
            if a['name'] != b['name']:
                print "name different, '%s' is different to '%s'" % (a['name'], b['name'])
                if a['version'] != b['version']:
                    print "version different, '%s' is different to '%s'" % (a['version'], b['version'])
                if a['release'] != b['release']:
                    print "release different, '%s' is different to '%s'" % (a['release'], b['release'])
                if a.get('arch',a.get('arch_label')) != b.get('arch',b.get('arch_label')):
                    print "arch different, '%s' is different to '%s'" % (a.get('arch',a.get('arch_label')), b.get('arch',b.get('arch_label')))
                if a['epoch'] != b['epoch']:
                    if a['epoch'] in ['',None] and b['epoch'] in ['',None]:
                        print "epochs are different but set to empty values (exception in matches)"
                    else:
                        print "epochs are different, '%s' is different to '%s'" % (a['epoch'],b['epoch'])
        return False



def api_restore(bkp, conn):
    """attempts to re-add the packages using the data exported into the bkp"""
    global verbose
    for package in bkp.packages:
        matched = False
        channels = bkp.packages[package]['channels']
        infos = bkp.packages[package]['packageinfo']
        try:
            pkgmatches = conn.client.packages.search.advanced(conn.key, _lucenestr(infos))
        except:
            #timeout problem, try again with a new session
            try:
                conn.reconnect()
                pkgmatches = conn.client.packages.search.advanced(conn.key, _lucenestr(infos))
            except:
                raise
            pass
        for match in pkgmatches:
            if match['provider'] == "Red Hat Inc.":
                #if this is the correct provider
                if match['id'] == package:
                    #if that is the same id as the package just add that and move on
                    if verbose:
                        print "match has same ID as stored, restoring"
                    _api_add(match['id'], channels, conn)
                    matched = True
                    break
                elif _cmp_pkginfo(match,infos):
                    #if that is the same package...
                    _api_add(match['id'], channels, conn)
                    matched = True
                    break
            else:
                if verbose:
                    print "match %s of provider %s discarded" % (_pkgname(match), match['provider'])
                continue
        else:
            #fallback to packages.findByNvrea because there were no matches
            if verbose:
                print "no match found for package %s with lucene, falling back to packages.findByNvrea" % (_pkgname(infos))
            try:
                if infos['epoch'] is None:
                    #no need to replace arch here. infos is data from the db.
                    pkgmatches = conn.client.packages.findByNvrea(conn.key, infos['name'], infos['version'], infos['release'], '' , infos['arch'])
                else:
                    #no need to replace arch here. infos is data from the db.
                    pkgmatches = conn.client.packages.findByNvrea(conn.key, infos['name'], infos['version'], infos['release'], infos['epoch'], infos['arch'])
            except:
                try:
                    conn.reconnect()
                    if infos['epoch'] is None:
                        #no need to replace arch here. infos is data from the db.
                        pkgmatches = conn.client.packages.findByNvrea(conn.key, infos['name'], infos['version'], infos['release'], '' , infos['arch'])
                    else:
                        #no need to replace arch here. infos is data from the db.
                        pkgmatches = conn.client.packages.findByNvrea(conn.key, infos['name'], infos['version'], infos['release'], infos['epoch'], infos['arch'])
                except:
                    raise
                pass
            for match in pkgmatches:
                if match['provider'] == "Red Hat Inc.":
                    #if this is the correct provider
                    if match['id'] == package:
                        #if that is the same id as the package just add that and move on
                        if verbose:
                            print "match has same ID as stored, restoring"
                        _api_add(match['id'], channels, conn)
                        matched = True
                        break
                    elif _cmp_pkginfo(match,infos):
                        #if that is the same package...
                        _api_add(match['id'], channels, conn)
                        matched = True
                        break
                else:
                    if verbose:
                        print "match %s of provider %s discarded" % (_pkgname(match), match['provider'])
                    continue
            else:
                print "no match found for package %s" % (_pkgname(infos)) 
        if matched:
            print "matched %s" %(_pkgname(infos))
        elif len(pkgmatches) >= 1 and verbose:
            #this will always be with either lucene that has found 0 matches or with the packages.findByNvrea method
            print "no match found for package %s within %d results" % (_pkgname(infos), len(pkgmatches))

def api_restore_alt(bkp,conn):
    """attempts to re-add the packages using the data exported into the bkp using another way to find the package"""
    global verbose
    for package in bkp.packages:
        matched = False
        channels = bkp.packages[package]['channels']
        infos = bkp.packages[package]['packageinfo']
        try:
            if infos['epoch'] is None:
                #no need to replace arch here. infos is data from the db.
                pkgmatches = conn.client.packages.findByNvrea(conn.key, infos['name'], infos['version'], infos['release'], '' , infos['arch'])
            else:
                #no need to replace arch here. infos is data from the db.
                pkgmatches = conn.client.packages.findByNvrea(conn.key, infos['name'], infos['version'], infos['release'], infos['epoch'], infos['arch'])
        except:
            try:
                conn.reconnect()
                if infos['epoch'] is None:
                    #no need to replace arch here. infos is data from the db.
                    pkgmatches = conn.client.packages.findByNvrea(conn.key, infos['name'], infos['version'], infos['release'], '' , infos['arch'])
                else:
                    #no need to replace arch here. infos is data from the db.
                    pkgmatches = conn.client.packages.findByNvrea(conn.key, infos['name'], infos['version'], infos['release'], infos['epoch'], infos['arch'])
            except:
                raise
            pass
        for match in pkgmatches:
            if match['provider'] == "Red Hat Inc.":
                #if this is the correct provider
                if match['id'] == package:
                    #if that is the same id as the package just add that and move on
                    if verbose:
                        print "match has same ID as stored, restoring"
                    _api_add(match['id'], channels, conn)
                    matched = True
                    break
                elif _cmp_pkginfo(match,infos):
                    #if that is the same package...
                    _api_add(match['id'], channels, conn)
                    matched = True
                    break
            else:
                if verbose:
                    print "match %s of provider %s discarded" % (_pkgname(match), match['provider'])
                continue
        else:
            print "no match found for package %s" % (_pkgname(infos)) 
        if matched:
            print "matched %s" %(_pkgname(infos))
        elif len(pkgmatches) >= 1:
            print "no match found for package %s within %d results" % (_pkgname(infos), len(pkgmatches))

                

#the main function of the program
def main(versioninfo):
    import optparse
    parser = optparse.OptionParser(description="This script will backup a list of packages before removing them from the database.\n REMEMBER TO BACKUP YOUR DATABASE BEFORE USING IT", version="%prog "+versioninfo)
    global_group = optparse.OptionGroup(parser, "General options", "Can be used in all calls, are not required")
    global_group.add_option("-v", "--verbose", dest="verbose", action="store_true", default=False, help="Enables debug output")
    global_group.add_option("-f","--file", dest="backupfile", type="string", help="File to use to save / load the data. Will be overwritten if exists previously!")
    #connection details
    connect_group = optparse.OptionGroup(parser, "Connection options", "Those options are required when running the restore part")
    connect_group.add_option("-H", "--host", dest="sathost", type="string", help="hostname of the satellite to use - use if localhost does not work", default="localhost")
    connect_group.add_option("-L", "--login", dest="satuser", type="string", help="User to connect to the satellite API")
    connect_group.add_option("-P", "--password", dest="satpwd", type="string", help="Password to connect to the satellite API")
    #group for the special actions
    advanced_group = optparse.OptionGroup(parser, "Actions", "Use only one of those")
    advanced_group.add_option("--list", dest="list", action="store_true", default=False, help="Loads the backup file and  lists its contents")
    advanced_group.add_option("--backup", dest="backup", action="store_true", default=False, help="Runs the backup and nothing else")
    advanced_group.add_option("--remove", dest="remove", action="store_true", default=False, help="Removes the rpms after taking a backup - requires confirmation at runtime")
    advanced_group.add_option("--restore", dest="restore", action="store_true", default=False, help="Attempts to add back the rpms from the backup - the packages must have been re-added correctly to the satellite before use.")
    advanced_group.add_option("--restore-alt", dest="restore_alt", action="store_true", default=False, help="Attempts to add back the rpms from the backup - the packages must have been re-added correctly to the satellite before use.\n Uses an alternative method for the search")
    advanced_group.add_option("--cleanup", dest="cleanup", action="store_true", default=False, help="Clears packages that don't have a channel from the backup file")
    parser.add_option_group(connect_group)
    parser.add_option_group(global_group)
    parser.add_option_group(advanced_group)
    (options, args) = parser.parse_args()
    global verbose 
    verbose = options.verbose
    if not options.backupfile:
        parser.error('The backup file needs to be specified')
    elif options.cleanup:
        bkphandle = PackagesInfo(options.backupfile)
        bkphandle.cleanup()
        bkphandle.save()
    elif options.restore:
        if not options.satuser or not options.satpwd:
            parser.error('Username and password are required options when restoring the removed packages')
        else:
            bkphandle = PackagesInfo(options.backupfile)
            conn = RHNSConnection(options.satuser,options.satpwd,options.sathost)
            api_restore(bkphandle,conn)
    elif options.restore_alt:
        if not options.satuser or not options.satpwd:
            parser.error('Username and password are required options when restoring the removed packages')
        else:
            bkphandle = PackagesInfo(options.backupfile)
            conn = RHNSConnection(options.satuser,options.satpwd,options.sathost)
            api_restore_alt(bkphandle,conn)
    elif options.list:
        bkphandle = PackagesInfo(options.backupfile)
        bkphandle.list()
    elif options.backup:
        #init of the config required in the db functions
        rhnConfig.initCFG()
        bkphandle = PackagesInfo(options.backupfile)
        db_backup(bkphandle)
        bkphandle.save()
    elif options.remove:
        #init of the config required in the db functions
        rhnConfig.initCFG()
        bkphandle = PackagesInfo(options.backupfile)
        db_clean(bkphandle)
    else:
        parser.error('You need to specify an action')

if __name__ == "__main__":
    main(__version__)

