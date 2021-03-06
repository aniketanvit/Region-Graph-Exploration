import graph_tool.all as gt
import json
import numpy as np
from collections import Counter
from subprocess import Popen, PIPE
from HierarchicalPartitioningTree import PartitionTree, PartitionNode
"""Helpers

This module provides helper functions.
"""


def statistics(G):
    """Provides general graph statistics.

    Args:
        G (graph_tool.Graph): The graph instance.

    Returns:
        An object with describing many statistical properties of the graph.
    """

    if not G:
        return 'No Graph Loaded'
    float_formatter = lambda x: '{:.2f}'.format(x)

    if G.get_vertex_filter()[0] is not None:
        vfilt = G.get_vertex_filter()[0]
        v_idx = np.where(vfilt.a == 1)[0]
    else:
        v_idx = np.arange(G.num_vertices())

    deg_counts, deg_bins = gt.vertex_hist(G, 'out', float_count=False)
    incl_idx = np.where(deg_counts != 0)[0]
    deg_bins = list(deg_bins[incl_idx])
    deg_counts = list(deg_counts[incl_idx])

    comp, cc_hist = gt.label_components(G)
    cc_size_counts = sorted(Counter(cc_hist).items())
    cc_sizes = [csc[0] for csc in cc_size_counts]
    cc_counts = [csc[1] for csc in cc_size_counts]

    num_cc = len(np.unique(comp.a))
    if deg_bins[0] == 0:
        num_singletons = deg_counts[0]
    else:
        num_singletons = 0

    if G.get_vertex_filter()[0] or G.get_edge_filter()[0]:
        # Always correct, but much slower
        peel_partition = kcore_decomposition(G)
        peel_bins = sorted(peel_partition.keys())
        peel_counts = [len(peel_partition[k]) for k in peel_bins]
    else:
        # NOTE:
        # Very fast, but unstable (not always accurate) for graphs with filters
        kcore = gt.kcore_decomposition(G)
        C = Counter(kcore.a[v_idx])
        peel_bins, peel_counts = [list(t) for t in zip(*C.items())]

    vlogv = G.num_vertices() * np.log2(G.num_vertices())

    return {
        'num_vertices': G.num_vertices(),
        'num_edges': G.num_edges(),
        'num_cc': num_cc,
        'num_singletons': num_singletons,
        'vlogv': float_formatter(vlogv),
        'deg_bins': deg_bins,
        'deg_counts': deg_counts,
        'cc_sizes': cc_sizes,
        'cc_counts': cc_counts,
        'peel_bins': peel_bins,
        'peel_counts': peel_counts,
    }


def kcore_decomposition(G, vlist=[], elist=[]):
    """Peform kcore decomposition (aka graph vertex peeling) on subgraph of G
    induced by input vertex and edge indices.

    Args:
        G (graph_tool.Graph): The graph instance.
        vlist (list): List of vertex indices to induce upon.
        elist (list): List of edge indices to induce upon.

    Returns:
        Dict with keys as kcore values and values as vertex IDs.
    """

    # initiate filters, if necessary
    if vlist or elist:
        vp = G.new_vp('bool', vals=False)
        ep = G.new_ep('bool', vals=False)
        if vlist is []:
            vlist = np.ones_like(vp.a)
        elif elist is []:
            elist = np.ones_like(ep.a)
        vp.a[vlist] = True
        ep.a[elist] = True
        G.set_vertex_filter(vp)
        G.set_edge_filter(ep)

    cmd = './app/bin/graph_peeling.bin -t core -o core'
    p = Popen([cmd], shell=True, stdout=PIPE, stdin=PIPE)
    for e in G.edges():
        p.stdin.write('{} {}\n'.format(e.source(), e.target()))
        p.stdin.flush()
    p.stdin.close()

    peel_partition = {}
    while True:
        line = p.stdout.readline()
        if line == '':
            break
        if not line.startswith('Core'):
            continue
        peel, vertices = line.split(' = ')
        peel = int(peel.split('_')[-1])
        vertices = vertices.strip().split()
        peel_partition[peel] = vertices

    return peel_partition


def traverse_tree(T, fully_qualified_label):
    """Traverse hierarchy to find PartitionNode with given label.

    Args:
        T (PartitionTree): The hierarchy tree instance.
        fully_qualified_label (str): Full name of the PartitionNode.

    Returns:
        PartitionNode with given label.
    """

    if fully_qualified_label.lower() == 'root':
        return T.root
    sub_ids = fully_qualified_label.split('|')
    if sub_ids[0].lower() == 'root':
        sub_ids = sub_ids[1:]
    node = T.root
    for s in xrange(len(sub_ids)):
        idx = int(sub_ids[s].split('_')[-1])
        node = node.children[idx]
    return node


def get_indices(T, fully_qualified_label):
    """Traverse hierarchy to find PartitionNode with given label and return its
    vertex and edge indices.

    Args:
        T (PartitionTree): The hierarchy tree instance.
        fully_qualified_label (str): Full name of the PartitionNode.

    Returns:
        vlist, elist: vertex and edge lists, respectively.
    """

    node = traverse_tree(T, fully_qualified_label)
    if len(node.vertex_indices) != 0:
        vlist = node.vertex_indices
        elist = node.edge_indices
    else:
        vlist, elist = PartitionTree.collect_indices(node)
    return vlist, elist


def save_adjacency(G, vlist, elist, filename):
    """Induce subgraph of G using input vertex and edge lists and save the
    resulting adjacency list to a file.

    Args:
        G (graph_tool.Graph): The graph instance.
        vlist (list): List of vertex indices to induce upon.
        elist (list): List of edge indices to induce upon.
        filename (str): Filepath to write adjacency.

    Returns:
        Confirmation or error message.
    """

    # get proper indices
    vp = G.new_vp('bool', vals=False)
    ep = G.new_ep('bool', vals=False)
    vp.a[vlist] = True
    ep.a[elist] = True
    G.set_vertex_filter(vp)
    G.set_edge_filter(ep)

    with open(filename, 'w') as f:
        for v in G.vertices():
            neighbors = [u for u in v.out_neighbours()]
            # First column for v; following columns are neighbors.
            # NOTE: Adjacency list is redundant for undirected graphs
            out_str = ('{} ' +
                       ('{} ' * len(neighbors))[:-1] +
                       '\n').format(v, *neighbors)
            f.write(out_str)

    return {'msg': 'Adjacency saved as {}'.format(filename)}


def to_vis_json(G, filename=None):
    """Produce Vis.js formatted network data (general).

    Args:
        G (graph_tool.Graph): The graph instance.

    Returns:
        Vis.js formatted network data.
    """

    nodes = []
    for v in G.vertices():
        # v_id = G.vp['id'][v]
        # label = v_id
        v_id = G.vertex_index[v]
        label = G.vp['id'][v]
        group = 1
        title = label
        value = v.out_degree()
        nodes.append({
            'id': v_id,
            'label': label,
            'title': title,
            'value': value,
            'group': group,
        })

    edges = []
    for e in G.edges():
        # src = G.vp['id'][e.source()]
        # tar = G.vp['id'][e.target()]
        src = G.vertex_index[e.source()]
        tar = G.vertex_index[e.target()]
        edges.append({
            'id': G.edge_index[e],
            'from': src,
            'to': tar,
            # 'value': 1,
        })

    return {'nodes': nodes, 'edges': edges}


def to_vis_json_bcc_tree(G, filename=None):
    """Produce Vis.js formatted network data (for BCC trees).

    Args:
        G (graph_tool.Graph): The graph instance.

    Returns:
        Vis.js formatted network data.
    """

    AP_GROUP = 0
    BCC_METANODE_GROUP = 1
    nodes = []
    for v in G.vertices():
        v_id = G.vertex_index[v]
        count = G.vp['count'][v]
        is_art = G.vp['is_articulation'][v]
        if is_art:
            label = G.vp['id'][v]
            title = 'AP: {}'.format(label)
            group = AP_GROUP
        else:
            title = 'BCC: {} | Count: {}'.format(v_id, count)
            label = title
            group = BCC_METANODE_GROUP
        value = count
        nodes.append({
                'id': v_id,
                'label': label,
                'title': title,
                'value': value,
                'group': group,
        })

    edges = []
    for e in G.edges():
        src = G.vertex_index[e.source()]
        tar = G.vertex_index[e.target()]
        edges.append({
                'id': G.edge_index[e],
                'from': src,
                'to': tar,
                'value': G.ep['count'][e],
            })

    return {'nodes': nodes, 'edges': edges}


def to_vis_json_cluster_map(G,
                            cluster_assignment,
                            landmark_map,
                            spine,
                            branches):
    """Produce Vis.js formatted network data (for clusters).

    Args:
        G (graph_tool.Graph): The graph instance.
        cluster_assignment (dict): Mapping of vertices to clusters.
        landmark_map (set): Set containing landmark vertices.
        spine (set): Set containing edges on spine.
        branches (set): Set containing edges on spinal branches.

    Returns:
        Vis.js formatted network data.
    """

    nodes = []
    for v in G.vertices():
        v_id = G.vertex_index[v]
        label = G.vp['id'][v]
        title = label
        value = v.out_degree()
        group = cluster_assignment[v_id]
        if v_id in landmark_map:
            shape = 'star'
            border_width = 2
        else:
            shape = 'dot'
            border_width = 1
        nodes.append({
            'id': v_id,
            'label': label,
            'title': title,
            'value': value,
            'group': group,
            'shape': shape,
            'borderWidth': border_width,
        })

    edges = []
    for e in G.edges():
        src = G.vertex_index[e.source()]
        tar = G.vertex_index[e.target()]
        if e in spine:
            category = 'spine'
        elif e in branches:
            category = 'branch'
        else:
            category = 'none'
        edges.append({
            'id': G.edge_index[e],
            'from': src,
            'to': tar,
            'category': category,
            # 'value': 1,
        })

    return {'nodes': nodes, 'edges': edges}


def to_vis_json_metagraph(metanodes, cross_edges):
    """Produce Vis.js formatted network data (for children metagraphs).

    Args:
        metanodes (dict): Metanodes of the metagraph.
        cross_edges (dict): Edges running between metanodes.

    Returns:
        Vis.js formatted network data.
    """

    nodes = []
    for mn_id, node_info in metanodes.iteritems():
        long_label = node_info['fully_qualified_label']
        title_html = \
            '<p>{}<br>|V|: {}<br>|E|: {}'.format(long_label,
                                                 node_info['num_vertices'],
                                                 node_info['num_edges'])
        nodes.append({
            'id': mn_id,
            'label': node_info['short_label'],
            'title': title_html,
            'value': node_info['num_vertices'],
        })

    edges = []
    for idx, (e, edge_indices) in enumerate(cross_edges.iteritems()):
        value = len(edge_indices)
        edges.append({
            'id': idx,
            'from': e[0],
            'to': e[1],
            'value': value,
            'title': 'meta-edge size: {}'.format(value),
        })

    return {'nodes': nodes, 'edges': edges}
