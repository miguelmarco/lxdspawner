from jupyterhub.spawner import Spawner
import os
from traitlets import Bool, Unicode, List, Dict
import subprocess
from tornado import gen
import pwd
import grp
import time
import asyncio

class LxdSpawner(Spawner):
    """
    A Jupyterhub spawner that runs each user's session in a lxd container
    """
    image = Unicode("", config = True, help = "Image to run")

    files_to_push = List([], config = True,  help = "Files to push to the container, with the path to push them to")

    filesystems_to_mount = List([], config = True, help = "Filesystems to mount, with (name, source, path) format")

    privileged_container = Bool(False, config = True, help = "Wether to run the container as privileged (that is, with the same uid space as the host) or not")

    async def get_uid_gid(self):
        uid = pwd.getpwnam(self.user.name)[2]
        gid = grp.getgrnam(self.user.name)[2]
        return uid, gid

    async def run_command(self, lcmd, env=None):
        cmd = ''
        for l in lcmd:
            cmd += l+' '
        proc = await asyncio.create_subprocess_shell(cmd,
                                                    stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.PIPE)
        inbytes=None

        try:
            out, eout = await proc.communicate()
        except:
            self.log.debug("Exception raised when trying to run command: %s" % command)
            proc.kill()
            self.log.debug("Running command failed done kill")
            out, eout = await proc.communicate()
            out = out.decode.strip()
            eout = eout.decode.strip()
            self.log.error("Subprocess returned exitcode %s" % proc.returncode)
            self.log.error('Stdout:')
            self.log.error(out)
            self.log.error('Stderr:')
            self.log.error(eout)
            raise RuntimeError('{} exit status {}: {}'.format(cmd, proc.returncode, eout))
        else:
            eout = eout.decode().strip()
            err = proc.returncode
            if err != 0:
                self.log.error("Subprocess returned exitcode %s" % err)
                self.log.error(eout)
                raise RuntimeError(eout)

        out = out.decode().strip()
        return out


    async def start(self):
        self.log.debug("self.user {}".format(self.user.__dict__))
        self.log.debug("Running {}".format(["lxc", "init", self.image, 'lxdspawner_'+self.user.name]))
        await self.run_command(["lxc", "init", self.image, 'lxdspawner_'+self.user.name])
        self.log.debug("Running {}".format(["lxc", "list", "--format", "csv", "-c", "n4"]))
        for f in self.files_to_push:
            self.log.debug("Running {}".format(["lxc", "file", "push", f[0], 'lxdspawner_'+self.user.name+'/'+f[1]]))
            await self.run_command(["lxc", "file", "push", f[0], 'lxdspawner_'+self.user.name+'/'+f[1]])
        for m in self.filesystems_to_mount:
            self.log.debug("Running {}".format(["lxc", "config", "device", "add", 'lxdspawner_'+self.user.name, m[0], "disk", "source="+m[1], "path="+m[2]]))
            await self.run_command(["lxc", "config", "device", "add", 'lxdspawner_'+self.user.name, m[0], "disk", "source="+m[1], "path="+m[2]])
        if self.mem_limit:
            self.log.debug("Running {}".format(["lxc", "config", "set", 'lxdspawner_'+self.user.name, "limits.memory", str(self.mem_limit//1048576)]))
            await self.run_command(["lxc", "config", "set", 'lxdspawner_'+self.user.name, "limits.memory", str(self.mem_limit//1048576)+"MB"])
        if self.cpu_limit:
            self.log.debug("Running {}".format(["lxc", "config", "set", 'lxdspawner_'+self.user.name, "limits.cpu", str(int(self.cpu_limit))]))
            await self.run_command(["lxc", "config", "set", 'lxdspawner_'+self.user.name, "limits.cpu", str(int(self.cpu_limit))])
        self.port = 3080
        uid, gid = await self.get_uid_gid()
        cmd = ["lxc", "exec", 'lxdspawner_'+self.user.name, "--cwd", '/home/'+self.user.name, "--user", str(uid), "--group", str(gid)]
        for var in self.get_env():
            cmd.extend(['--env', '{}={}'.format(var,self.get_env()[var])])
        cmd.extend(['--env', 'HOME=/home/{}'.format(self.user.name)])
        cmd.extend(['--'])
        cmd.extend(self.cmd)
        cmd.extend(self.get_args())
        cmd.extend(["--ip=''"])
        cmd.extend(['--debug'])
        #cmd.extend(['"{}"'.format(' '.join(w for w in self.cmd+self.get_args()))])
        if self.privileged_container:
            self.log.debug("Running {}".format(["lxc", "config", "set", 'lxdspawner_'+self.user.name, "security.privileged", "true"]))
            await self.run_command(["lxc", "config", "set", 'lxdspawner_'+self.user.name, "security.privileged", "true"])
        self.log.debug("Running {}".format(["lxc", "start", 'lxdspawner_'+self.user.name]))
        await self.run_command(["lxc", "start", 'lxdspawner_'+self.user.name])
        ip = ''
        while ip == '':
            res = await self.run_command(["lxc", "list", "--format", "csv", "-c", "n4"])
            lines = res.splitlines()
            lines = [l.split(',') for l in lines]
            self.log.debug("user.name = {}".format(self.user.name))
            self.log.debug("lines:::::")
            self.log.debug(lines)
            ip = [l[1].split(' ') for l in lines if l[0] == 'lxdspawner_'+self.user.name][0][0]
            self.log.debug("ip : {}".format(ip))
        self.ip = ip
        self.log.debug("ip : {}".format(self.ip))
        self.log.debug("cmd : {}".format(cmd))
        lcmd = ''
        for l in cmd:
            lcmd += l+' '
        self.proc = await asyncio.create_subprocess_shell(lcmd)
        self.log.debug("created async process with command: {}".format(lcmd))
        await gen.sleep(5)
        self.log.debug("waited 5 seconds")
        return (self.ip, self.port)


    async def stop(self):
        await self.run_command(["lxc", "stop", 'lxdspawner_'+self.user.name])
        await self.run_command(["lxc", "delete", 'lxdspawner_'+self.user.name])
        return

    async def poll(self):
        res = subprocess.run(["lxc", "list", "--format", "csv", "-c", "ns"], capture_output=True)
        lines = res.stdout.decode('utf-8').splitlines()
        lines = [l.split(',') for l in lines]
        status = [l[1] for l in lines if l[0] == 'lxdspawner_'+self.user.name]
        self.log.debug("Polling {}. Container status = {}".format('lxdspawner_'+self.user.name, status))
        if not status:
            return 1
        if len(status) == 1 and status[0] == 'RUNNING':
            return None
        else:
            subprocess.run(["lxc", "stop", 'lxdspawner_'+self.user.name])
            subprocess.run(["lxc", "delete", 'lxdspawner_'+self.user.name])
            return 1

