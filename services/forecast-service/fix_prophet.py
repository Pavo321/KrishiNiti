import pathlib
import shutil
import sys

stan_model = pathlib.Path('/usr/local/lib/python3.11/site-packages/prophet/stan_model')

if not stan_model.exists():
    print('stan_model not found, skipping cmdstan fix')
    sys.exit(0)

cmdstan = stan_model / 'cmdstan-2.33.1'
cmdstan.mkdir(parents=True, exist_ok=True)
(cmdstan / 'makefile').touch()

bin_dir = cmdstan / 'bin'
bin_dir.mkdir(exist_ok=True)

stanc_src = bin_dir / 'linux-stanc'
stanc_dst = bin_dir / 'stanc'

if not stanc_dst.exists() and stanc_src.exists():
    shutil.copy(stanc_src, stanc_dst)
    print('cmdstan path fixed')
