import os
import shutil


def merge_zstat_to_unified_dir(
    ds_prefix, zstatmap_root=None, out_dir=None, use_symlink=True
):
    """
    Merge all zmap files from all task/node-dataLevel under z_statmap/{ds_prefix}/
    into z_statmap/{ds_prefix}/ALL_combined/node-dataLevel/
    Task info is inserted into filename for readability: contrast-<contrast>_<task>_stat-z_statmap.nii.gz
    """
    if zstatmap_root is None:
        zstatmap_root = f"llm_cogitive_function/data/z_statmap/{ds_prefix}"
    if out_dir is None:
        out_dir = os.path.join(zstatmap_root, "ALL_combined", "node-dataLevel")
    os.makedirs(out_dir, exist_ok=True)
    count = 0
    for task_dir in os.listdir(zstatmap_root):
        task_path = os.path.join(zstatmap_root, task_dir, "node-dataLevel")
        if not os.path.isdir(task_path):
            continue
        task_name = task_dir.replace("task-", "")
        for fname in os.listdir(task_path):
            if fname.startswith("contrast-") and fname.endswith(
                "_stat-z_statmap.nii.gz"
            ):
                src = os.path.abspath(os.path.join(task_path, fname))
                prefix = "contrast-"
                suffix = "_stat-z_statmap.nii.gz"
                contrast = fname[len(prefix) : -len(suffix)]
                fname_with_task = f"{prefix}{contrast}_{task_name}{suffix}"
                dst = os.path.join(out_dir, fname_with_task)
                if os.path.exists(dst):
                    print(f"Skip existing: {dst}")
                    continue
                if use_symlink:
                    os.symlink(src, dst)
                else:
                    shutil.copy2(src, dst)
                print(f"{'Linked' if use_symlink else 'Copied'}: {src} -> {dst}")
                count += 1
    print(f"Total {count} zmap files merged to {out_dir}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ds_prefix", type=str, required=True, help="Dataset prefix, e.g. ds000002"
    )
    parser.add_argument(
        "--zstatmap_root",
        type=str,
        default=None,
        help="Root dir for z_statmap/{ds_prefix}",
    )
    parser.add_argument(
        "--out_dir", type=str, default=None, help="Output dir for merged zmap files"
    )
    parser.add_argument(
        "--copy", action="store_true", help="Copy files instead of symlink"
    )
    args = parser.parse_args()
    merge_zstat_to_unified_dir(
        ds_prefix=args.ds_prefix,
        zstatmap_root=args.zstatmap_root,
        out_dir=args.out_dir,
        use_symlink=not args.copy,
    )
