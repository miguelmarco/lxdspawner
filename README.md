# LXD spawner for jupyterhub

This implements a jupyterhub spawner based on LXD containers.

It requires the machine where jupyterhub runs to have LXD installed and running, with one container image that can run the standalone jupyter server (plus the kernels you want to run in it).

The spawner will create a new container for each user and run the standalone jupyter server in it. After finishing, the container will be deleted.

If LXD is configured as part of a cluster, the container will be run in the cluster node with less containers running.

## Installation

The easyest way to install it is with pip. From the directory of this repository, running

```
pip3 install .
```

As usual, you can make an install just for one user with the `--user` flag.

## Configuration

The following options can be configured, by adding the corresponding lines to the `jupyterhub_config.py` file:

- The container image that will be used to launch the containers can be set like this:

```
c.LxdSpawner.image = 'container_image_name'
```

- Some files can be copied to the container before starting it. For example, to push the `/etc/passwd` and `/etc/group` would allow to ensure the same mapping between usernames and uid's as in the host (notice that for this example to work, it require the `privileged_containers` option set to `True`). It can be achived by setting

```
c.LxdSpawner.files_to_push = [['/etc/passwd', '/etc/passwd'], ['/etc/group', '/etc/group']]
```

Each entry corresponds to a file that will be copied from the host, and the path to copy it to inside the container.

Since the files are copied from whatever host runs the container, you should make sure that the files exist (and have the correct contain) in all hosts.

- Some directories in the host can be mounted inside the container (for example, if you want to have persistence in the `/home` directory. It can be done with the option

```
c.LxdSpawner.filesystems_to_mount = [['name', 'directory', 'path']]
```

Each entry of that list corresponds to a mount point. In that example, the `directory` in the host will be mounted in the `path` inside the container. `name` is the name that the mountpoint  will have.

As before, you must make sure that the directory exists in the host. One way to have persistence which is consistent along the hosts is to share a NFS directory between the hosts, and mount that directory inside the container.

Notice that processes inside the container will be run as a user that might not have permissions on that directories. Set the permissions accordingly.
