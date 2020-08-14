from jupyterhub.spawner import Spawner
import os
from traitlets import Any, Bool, Unicode, List, Dict
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

    process_limit = Int(300, config = True, help = "number of processes allowed in the container")

    async def get_uid_gid_coroutine(self):
        uid = pwd.getpwnam(self.user.name)[2]
        gid = grp.getgrnam(self.user.name)[2]
        return uid, gid

    get_uid_gid = Any(get_uid_gid_coroutine, config=True, help = "function to get the uid and gid to run inside the container")

    commands_to_prepare = List([], config = True, help = "commands to run once the container is started but before the jupyter standalone server is launched")

    post_hub_commands = List([], config = True, help = "Commands to be run by the hub right after spawning; {USERNAME} will be substituted.")

    host_weights = Dict({}, config = True, help = "Weight of each host for load balancing. Hosts not included here are considered with a weight of 1.0")

    async def run_command(self, lcmd, env=None):
        cmd = ''
        for l in lcmd:
            cmd += l+' '
        self.log.debug("Running {}".format(lcmd))
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
        existing_containers_csv = await self.run_command(["lxc", "list", "--format", "csv"])
        existing_containers_lines = existing_containers_csv.splitlines()
        existing_containers_names = [l.split(',')[0] for l in existing_containers_lines]
        if "lxdspawner-"+self.user.name in existing_containers_names:
            self.log.debug("user's container already exists, deleting")
            await self.run_command(["lxc", "delete", "lxdspawner-"+self.user.name, "--force"])
        existing_hosts_csv = await self.run_command(["lxc", "cluster", "list", "--format", "csv"])
        existing_hosts_lines = [l.split(',') for l in existing_hosts_csv.splitlines()]
        existing_hosts_names = [l[0] for l in existing_hosts_lines if l[3]=='ONLINE']
        self.log.debug("Existing hosts: {}".format(existing_hosts_names))
        host_loads = {h:0.0001 for h in existing_hosts_names}
        self.log.debug("host_loads {}".format(host_loads))
        loads = await self.run_command(["lxc", "list",  "--format", "csv", "-c", "L"])
        self.log.debug("loads {}".format(loads))
        hosts_weights = dict([])
        for l in loads.splitlines():
            if l in host_loads:
                host_loads[l] = host_loads[l]+1.0
        self.log.debug("host_loads {}".format(host_loads))
        for l in existing_hosts_names:
            if not l in self.host_weights:
                hosts_weights[l] = 1.0
            else:
                hosts_weights[l] = float(self.host_weights[l])
        self.log.debug("hosts_weights {}".format(hosts_weights))
        hosts_relative_load = {h: hosts_weights[h]/host_loads[h] for h in existing_hosts_names}
        self.log.debug("Relative load of hosts: {}".format(hosts_relative_load))
        select_host = max(hosts_relative_load, key = lambda h: hosts_relative_load[h])
        self.log.debug("Selected {} for having the highest relative availability".format(select_host))
        await self.run_command(["lxc", "init", self.image, 'lxdspawner-'+self.user.name, "--target", select_host])
        for f in self.files_to_push:
            await self.run_command(["lxc", "file", "push", f[0], 'lxdspawner-'+self.user.name+'/'+f[1]])
        for m in self.filesystems_to_mount:
            await self.run_command(["lxc", "config", "device", "add", 'lxdspawner-'+self.user.name, m[0], "disk", "source="+m[1], "path="+m[2]])
        if self.mem_limit:
            await self.run_command(["lxc", "config", "set", 'lxdspawner-'+self.user.name, "limits.memory", str(self.mem_limit//1048576)+"MB"])
        if self.cpu_limit:
            await self.run_command(["lxc", "config", "set", 'lxdspawner-'+self.user.name, "limits.cpu", str(int(self.cpu_limit))])
        if self.process_limit:
            await self.run_command(["lxc", "config", "set", "lxdspawner-"+self.user.name, "limits.process", str(int(self.process_limit))]
        self.port = 3080
        uid, gid = await self.get_uid_gid(self)
        cmd = ["lxc", "exec", 'lxdspawner-'+self.user.name, "--cwd", '/home/'+self.user.name, "--user", str(uid), "--group", str(gid)]
        for var in self.get_env():
            cmd.extend(['--env', '{}={}'.format(var,self.get_env()[var])])
        cmd.extend(['--env', 'HOME=/home/{}'.format(self.user.name)])
        cmd.extend(['--env', 'SHELL=/bin/bash'])
        cmd.extend(['--'])
        cmd.extend(self.cmd)
        cmd.extend(self.get_args())
        cmd.extend(["--ip=''"])
        cmd.extend(['--debug'])
        #cmd.extend(['"{}"'.format(' '.join(w for w in self.cmd+self.get_args()))])
        if self.privileged_container:
            await self.run_command(["lxc", "config", "set", 'lxdspawner-'+self.user.name, "security.privileged", "true"])
        await self.run_command(["lxc", "start", 'lxdspawner-'+self.user.name])
        for command in self.commands_to_prepare:
            scom = command.replace("{USERNAME}", self.user.name)
            await self.run_command(["lxc", "exec", 'lxdspawner-'+self.user.name, "--user", str(uid), "--group", str(gid), "--", scom])
        ip = ''
        while ip == '':
            res = await self.run_command(["lxc", "list", "--format", "csv", "-c", "n4"])
            lines = res.splitlines()
            lines = [l.split(',') for l in lines]
            ip = [l[1].split(' ') for l in lines if l[0] == 'lxdspawner-'+self.user.name][0][0]
        self.ip = ip
        lcmd = ''
        for l in cmd:
            lcmd += l+' '
        self.proc = await asyncio.create_subprocess_shell(lcmd)
        self.log.debug("created async process with command: {}".format(lcmd))
        await gen.sleep(5)
        self.log.debug("waited 5 seconds")
        for comm in self.post_hub_commands:
            await self.run_command([comm.replace("{USERNAME}", self.user.name)])
        return (self.ip, self.port)


    async def stop(self):
        await self.run_command(["lxc", "stop", 'lxdspawner-'+self.user.name, "--force"])
        await self.run_command(["lxc", "delete", 'lxdspawner-'+self.user.name, "--force"])
        return

    async def poll(self):
        res = await self.run_command(["lxc", "list", "--format", "csv", "-c", "ns"])
        lines = res.splitlines()
        lines = [l.split(',') for l in lines]
        status = [l[1] for l in lines if l[0] == 'lxdspawner-'+self.user.name]
        self.log.debug("Polling {}. Container status = {}".format('lxdspawner-'+self.user.name, status))
        if not status:
            return 1
        if len(status) == 1 and status[0] == 'RUNNING':
            return None
        else:
            self.stop()
            return 1

