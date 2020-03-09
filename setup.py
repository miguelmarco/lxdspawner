from setuptools import setup

setup_args = dict(
    name                = 'lxdspawner',
    packages            = ['lxdspawner'],
    version             = "0.1",
)



def main():
    setup(**setup_args)

if __name__ == '__main__':
    main()
