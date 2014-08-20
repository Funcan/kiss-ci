import json
import os
from  novaclient.v1_1 import client as novaclient
import paramiko
import sys
import time

class GerritEventStream(object):
    def __init__(self, username, host="review.openstack.org", port=29418, key=None):
        self.username = username
        self.host = host
        self.port = port

        if key is None:
            self.key = "%s/.ssh/id_dsa.pub" % os.environ['HOME']
        else:
            self.key = key

        print "Connecting to %s@%s:%d keyfile %s" % (username, host, port, self.key)

        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            self.ssh.connect(self.host, self.port, self.username)
        except paramiko.SSHException as e:
            print e
            sys.exit(1)

        self.stdin, self.stdout, self.stderr = self.ssh.exec_command("gerrit stream-events")

    def __iter__(self):
        return self

    def next(self):
        return self.stdout.readline()


def runtest(project, ref, revision):
    """ Build a node, run tests and comment on gerrit appropriately """

    print "Running test for project %s ref %s" % (project, ref)
    node = buildnode("test - %s" % ref, project, ref, revision)
    command = build_test_command(project, ref, revision)
    status = runcommand(command, node)
    uploadlogs(status, node, project, ref, revision)


def runcommand(command, node, user="ubuntu"):
    """ Run command on node and return the last line of stdout """

    print "ssh %s@%s '%s'" % (user, node, command)

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(node, 22, user)
    (stdin, stdout, stderr) = ssh.exec_command(command)

    return stdout.readlines()[-1]


def uploadlogs(status, node, project, ref, revision):
    """ Run upload logs script on node, then vote on gerrit """

    runcommand(node, "uploadlogs.py %s %s %s" % (status, project, ref))
    print "Gerrit voting not yet implemented: ref %s status %s"


def buildnode(name, project, ref, revision):
    """ Build a node and return an ssh connection string and command name to run the tests """
    username = os.environ["OS_USERNAME"]
    password = os.environ["OS_PASSWORD"]
    tenant = os.environ["OS_TENANT_NAME"]
    url = os.environ["OS_AUTH_URL"]
    region = os.environ.get("OS_REGION_NAME")

    client = novaclient.Client(username, password, tenant, url, region_name=region)
    client.authenticate() # Fail early if there's a problem

    image = "169d484a-dde2-44c8-8f15-daaa1ba69e94"
    flavor = "102"
    meta = {"Creator": "kiss-ci",
            "Project": project,
            "Ref": ref,
            "Revision": revision}

    print("Building node")
    node = client.servers.create(name, image, flavor, meta=meta)
    while node.status in "BUILD":
        node = client.servers.get(node.id)
        print("Waiting for node: %s" % node.status)
        time.sleep(10)
    if node.status != "ACTIVE":
        raise Exception("Node creation failed") # FIXME: We should handle this nicely
    print("Node built")

    ip = node.networks["default"][0] # This is very system specific it seems
    print "Got ip: %s" % ip
    return ip

def build_test_command(project, ref, revision):
    if project != "openstack/cinder":
        raise Exception("Don't know how to test project %s, this script only handles cinder")

    return "runtest.py %s %s" % (ref, revision)


##############################################################################


if __name__ == "__main__":
    events = GerritEventStream("duncan-thomas")

    for event in events:
        event = json.loads(event)
        if event["change"]["project"] != "openstack/cinder":
            continue

        if event["type"] == "comment-added":
            # This is where we could look of jenkins +1 votes
            continue

        if event["type"] == "patchset-created":
            runtest(project=event["change"]["project"],
                    ref=event["patchSet"]["ref"],
                    revision=event["patchSet"]["revision"])

