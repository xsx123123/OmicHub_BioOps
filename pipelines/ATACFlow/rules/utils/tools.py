#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
def get_java_opts(config, input, resources):
    """
    Get the correct Java options for a given rule.
    """
    mem_gb = max(int(resources.mem_mb / 1024) - 4, 2)
    
    if mem_gb > 50:
        mem_gb = 50 
        
    return f"-Xmx{mem_gb}g -XX:+UseParallelGC -XX:ParallelGCThreads=4"
    
def get_blacklist_path(config):
    """
    Get the blacklist path based on genome build
    """
    build = config.get("Genome_Version")
    blacklist_dict = config.get('Bowtie2_index',{}).get(build,{}).get("blacklists", {})

    if not blacklist_dict:
        return ""
    else:
        blacklist_dir = os.path.join(config.get("reference_path"),blacklist_dict)
    return blacklist_dir

def get_organelle_names(config):
    build = config.get("Genome_Version")
    genome_cfg = config.get("genome_info", {}).get(build, {})

    org_list = []
    for key in ["chrMID", "plast"]:
        val = genome_cfg.get(key)
        if val:
            if isinstance(val, list): org_list.extend(val)
            else: org_list.append(val)

    # Return as space-separated string for easier shell processing
    return " ".join(org_list) if org_list else ""