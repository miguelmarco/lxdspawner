from jupyterhub.spawner import Spawner
import os
from traitlets import Bool, Unicode, List, Dict
import subprocess
from tornado import gen
import pwd
import grp

class LxdSpawner(Spawner):
    """
    A Jupyterhub spawner that runs each user's session in a lxd container
    """
    image = Unicode("", config = True, help = "Image to run")

    files_to_push = List(
        trait = Unicode(),
        default_value = [],
        minlen = 0,
        config = True,
        help = "Files to push to the container, with the path to push them to"
    )

    filesytems_to_mount = List(
        trait = Unicode(),
        default_value = [],
        minlen = 0,
        config = True,
        help = "Filesystems to mount, with (name, source, path) format"
    )


    @gen.coroutine
    def start(self):
        subprocess.run(["lxc", "init", self.image, self.user.name])
        res = subprocess.run(["lxc", "list", "--format", "csv", "-c", "n4"], capture_output=True)
        lines = res.stdout.decode('utf-8').splitlines()
        lines = [l.split(',') for l in lines]
        self.ip = [l[1].split(' ') for l in lines if l[0] == self.user.name][0]
        for f in self.files_to_push:
            subprocess.run(["lxc", "push", f[0], self.user.name+'/'+f[1]])
        for m in self.filesystems_to_mount:
            subprocess.run(["lxc", "config", "device", "add", self.user.name, 
                m[0], "disk", "source="+m[1], "path="+m[2]])
        if self.mem_limit:
            subprocess.run(["lxc", "config", "set", self.user.name, "limits.memory", self.mem_limit])
        if self.cpu_limit:
            subprocess.run(["lxc", "config", "set", self.user.name, "limits.cpu", self.cpu_limit])
        self.port = '3080'
        uid = pwd.getpwnam(self.user.name)[2]
        gid = grp.getgrnam(self.user.name)[2]
        cmd = ["lxc", "exec", "--cwd", self.user.name, "--user", uid, "--group", gid]
        for var in self.get_env():
            cmd.extend(['--env', '{}={}'.format(var,self.get_env()[var])])
        cmd.extend(self.cmd)
        cmd.extend(self.get_args())
        subprocess.run(["lxc", "config", "set", self.user.name, "security.privileged", "true"])
        subprocess.run(["lxc", "start", self.user.name])
        subprocess.run(cmd)
        return (self.ip, self.port)

    @gen.coroutine
    def stop(self):
        subprocess.run(["lxd", "stop", self.user.name])
        subprocess.run(["lxd", "delete", self.user.name])
        return

    @gen.coroutine
    def poll(self):
        res = subprocess.run(["lxc", "list", "--format", "csv", "-c", "ns"], capture_output=True)
        lines = res.stdout.decode('utf-8').splitlines()
        lines = [l.split(',') for l in lines]
        status = [l[1] for l in lines if l[0] == self.user.name]
        if not status:
            return 1
        if status[0] == 'RUNNING':
            return None
        else:
            subprocess.run(["lxd", "stop", self.user.name])
            subprocess.run(["lxd", "delete", self.user.name])
            return 1
            
    
