import sys
import os
import argparse


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('root', help="the root CMIP6 directory path")
    parser.add_argument(
        'source', help="the source CMIP6 directory name ex v20190622")
    parser.add_argument(
        'destination', help="the destination CMIP6 directory name ex v20190815")
    parser.add_argument(
        '--dryrun', help="Dryrun mode will print the file moves but not actually move anything",
        action="store_true"
    )
    args = parser.parse_args(sys.argv[1:])

    for root, dirs, _ in os.walk(args.root):
        if not dirs:
            continue

        if args.source not in dirs or args.destination not in dirs:
            continue

        src_path = os.path.join(root, args.source)
        dst_path = os.path.join(root, args.destination)
        for f in os.listdir(src_path):
            old_path = os.path.join(src_path, f)
            new_path = os.path.join(dst_path, f)
            print("Moving {} to {}".format(old_path, new_path))
            if not args.dryrun:
                os.rename(old_path, new_path)
        
        if not args.dryrun:
            print("removing {}".format(src_path))
            os.rmdir(src_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())