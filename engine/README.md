# `sgr` Engine

This is an optional component for the `sgr` CLI that turns it into a
self-contained "lite" version of [Splitgraph](https://www.splitgraph.com). The
engine is a Docker image which is built from the Dockerfile in this repository.

The basic idea is to run the engine with specific credentials and db name (see
below) and to make sure the client is configured with those same credentials.

The published Docker image can be found on Docker Hub at
[splitgraph/engine](https://hub.docker.com/r/splitgraph/engine/)

## What's Inside

Currently, the engine is based on the
[official Docker Postgres image](https://hub.docker.com/_/postgres/), and
performs a few additional tasks necessary for running `sgr` and
[mounting external databases](https://www.splitgraph.com/docs/sgr-advanced/ingesting-data/foreign-data-wrappers/introduction)
(MongoDB/PostgreSQL/MySQL/Elasticsearch):

- Installs foreign data wrapper (FDW) extensions:
  - [EnterpriseDB/mongo_fdw](https://github.com/EnterpriseDB/mongo_fdw.git) to
    allow mounting of mongo databases
  - [postgres_fdw](https://www.postgresql.org/docs/12/static/postgres-fdw.html)
    to allow mounting of external postgres databases
  - [EnterpriseDB/mysql_fdw](https://github.com/EnterpriseDB/mysql_fdw.git) to
    allow mounting of MySQL (version 8) databases
  - [Kozea/Multicorn](https://github.com/Kozea/Multicorn.git) for a custom query
    handler that allows to query images without checking them out (layered
    querying), as well as allow others to write custom foreign data wrappers.
  - [Fork](https://github.com/splitgraph/postgres-elasticsearch-fdw) of
    [matthewfranglen/postgres-elasticsearch-fdw](https://github.com/matthewfranglen/postgres-elasticsearch-fdw)
    to mount Elasticsearch indexes
- Installs the
  [`sgr` command line client and library](https://github.com/splitgraph/sgr.git)
  that is required for layered querying.
- Optionally installs the [PostGIS](https://postgis.net/) extension to handle
  geospatial data: to build the engine with PostGIS, add `with_postgis=1` to
  your `make` command.

## Building the engine

Make sure you've cloned the engine with `--recurse-submodules` so that the Git
submodules in `./src/cstore_fdw` and `./src/Multicorn` are initialized. You can
also initialize and check out them after cloning by doing:

```
git submodule update --init
```

Then, run `make`. You can use environment variables `DOCKER_REPO` and
`DOCKER_TAG` to override the tag that's given to the engine.

## Running the engine

For basic cases, we recommend you to use
[`sgr engine`](https://www.splitgraph.com/docs/sgr/engine-management/engine-add)
to manage the engine Docker container.

You can also use `docker run`, or alternatively `docker-compose`.

For example, to run with forwarding from the host port `5432` to the
`splitgraph/engine` image using password `supersecure`, default user `sgr`, and
database `splitgraph` (see "environment variables"):

**Via `docker run`:**

```bash
docker run -d \
    -e POSTGRES_PASSWORD=supersecure \
    -p 5432:5432 \
    -e SG_CONFIG_FILE=/.sgconfig \
    -v $HOME/.splitgraph/.sgconfig:/.sgconfig  \
    splitgraph/engine
```

**Via `docker-compose`:**

```yml
engine:
  image: splitgraph/engine
  ports:
    - 5432:5432
  environment:
    - POSTGRES_PASSWORD=supersecure
    - SG_CONFIG_FILE=/.sgconfig
  volumes:
    - $HOME/.splitgraph/.sgconfig:/.sgconfig
```

And then simply run `docker-compose up -d engine`

Note that if you're logged into Splitgraph, you will need to manually **bind
mount your `.sgconfig` file** into the engine so that it knows how to
authenticate with data.splitgraph.com. This is done automatically with the
[`sgr engine`](https://www.splitgraph.com/docs/sgr/engine-management/engine-add)
wrapper. More information
[in the documentation](https://www.splitgraph.com/docs/sgr-advanced/configuration/introduction#in-engine-configuration).

**Important**: Make sure that your
[`sgr`` client](https://www.github.com/splitgraph/sgr) is configured to
connect to the engine using the credentials and port supplied when running it.

### Environment variables

All of the environment variables documented in the
[official Docker postgres image](https://hub.docker.com/_/postgres/) apply to
the engine. At the moment, there are no additional environment variables
necessary. Specifically, the necessary environment variables:

- `POSTGRES_USER`: Defaults to `sgr`
- `POSTGRES_DB`: Defaults to `splitgraph`
- `POSTGRES_PASSWORD`: Must be set by you

## Extending the engine

Because `splitgraph/engine` is based on the official Docker postgres image, it
behaves in the same way as
[documented on Docker Hub](https://hub.docker.com/_/postgres/). Specifically,
the best way to extend it is to add `.sql` and `.sh` scripts to
`/docker-entrypoint-initdb.d/`. These files are executed in executed in sorted
name order as defined by the current locale. If you would like to run your files
_after_ splitgraph init scripts, see the scripts in the `init_scripts`
directory. Splitgraph prefixes scripts with three digit numbers starting from
`000`, `001`, etc., so you should name your files accordingly.

You can either add these scripts at build time (i.e., create a new `Dockerfile`
that builds an image based on `splitgraph/engine`), or at run time by mounting a
volume in `/docker-entrypoint-initdb.d/`.

**Important Note:** No matter which method you use (extending the image or
mounting a volume), Postgres will only run these init scripts on the _first run_
of the container, so if you want to add new scripts you will need to `docker rm`
the container to force the initialization to run again.

### Adding additional init scripts at build time by creating a new image

Here is an example `Dockerfile` that extends `splitgraph/engine` and performs
some setup before and after the splitgraph init:

```Dockerfile
FROM splitgraph/engine

# Use 0000_ to force sorting before splitgraph 000_
COPY setup_before_splitgraph.sql /docker-entrypoint-initdb.d/0000_setup_before_splitgraph.sql

# Do not prefix with digits to force sorting after splitgraph xxx_
COPY setup_after_splitgraph.sql /docker-entrypoint-initdb.d/setup_after_splitgraph.sql
```

Then you can just build it and run it as usual (see "Running the engine"):

```
docker build . -t my-splitgraph-engine
```

### Adding additional init scripts at run time by mounting a volume

Just mount your additional init scripts in `/docker-entrypoint-initdb.d/` the
same as you would if you were adding them at build time (same lexiographical
rules apply):

**Via `docker run`:**

```bash
docker run -d \
    -v "$PWD/setup_before_splitgraph.sql:/docker-entrypoint-initdb.d/0000_setup_before_splitgraph.sql" \
    -v "$PWD/setup_after_splitgraph.sql:/docker-entrypoint-initdb.d/setup_after_splitgraph.sql" \
    -e POSTGRES_PASSWORD=supersecure \
    -p 5432:5432 \
    splitgraph/engine
```

**Via `docker compose`:**

```yml
engine:
  image: splitgraph/engine
  ports:
    - 5432:5432
  environment:
    - POSTGRES_PASSWORD=supersecure
  expose:
    - 5432
  volumes:
    - ./setup_before_splitgraph.sql:/docker-entrypoint-initdb.d/0000_setup_before_splitgraph.sql
    - ./setup_after_splitgraph.sql:/docker-entrypoint-initdb.d/setup_after_splitgraph.sql
```

And then `docker-compose up -d engine`

### More help

- Read the
  [Splitgraph and `sgr` documentation](https://www.splitgraph.com/docs/)
- Read the [Docker Postgres documentation](https://hub.docker.com/_/postgres/)
- Submit an issue
- Ask for help on our [Discord channel](https://discord.gg/4Qe2fYA)
