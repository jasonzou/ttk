from objects import Node, Edge, Constraint
from utils import intersect_relations
from utils import compare_id
from mappings import invert_interval_relations
from mappings import abbreviate_convex_relation
#from timeml_specs import EID, EVENTID
from library.timeMLspec import EID, EVENTID

DEBUG = True
DEBUG = False


class Graph:

    """Implements the graph object used in the constraint propagation algorithm.

    Instance variable:
       file - the name of the source file
       cycle - an integer
       queue - a list of Constraints
       nodes - a hash of Nodes, indexed on node identifiers
       edges - a hashs of hashes of Edges, indexed on node identifiers
       compositions - a CompositionTable
    """
    
    def __init__(self):

        """Initialize an empty graph, with empty queue, node list and edges
        hash."""

        self.file = None
        self.cycle = 0
        self.queue = []
        self.nodes = {}
        self.edges = {}
        self.compositions = None

        
    def add_nodes(self, events, instances, timexes):

        """Adds the events/instances and timexes to the nodes table. Also
        initializes the edges table now that all nodes are known."""

        for timex in timexes:
            #print 'T',timex
            node = Node(timex=timex)
            self.nodes[node.id] = node

        eid_to_instance = {}
        for instance in instances:
            eid_to_instance[instance.attrs[EVENTID]] = instance

        for event in events:
            instance = eid_to_instance[event.attrs[EID]]
            node = Node(event=event, instance=instance)
            self.nodes[node.id] = node

        for n1 in self.nodes.keys():
            self.edges[n1] = {}
            for n2 in self.nodes.keys():
                self.edges[n1][n2] = Edge(n1, n2, self)


    def propagate(self, constraint):

        """Propagate the constraint through the graph, using Allen's
        constraint propagation algorithm."""

        self.cycle += 1
        self.queue.append(constraint)
        #debug(str="\n%d  %s" % (self.cycle, constraint))

        while self.queue:

            constraint_i_j = self.queue.pop(0)
            constraint_i_j.cycle = self.cycle
            #debug(2, '')
            #debug(2, "POP QUEUE (cycle %d): %s" % (self.cycle, constraint_i_j))
            
            # compare new constraint to the one already on the edge
            edge_i_j = self.edges[constraint_i_j.node1][constraint_i_j.node2]
            intersection = self._intersect_constraints(edge_i_j, constraint_i_j)
            if not intersection:
                continue

            # instantiate the constraint on its edge, note that the
            # history of the constraint may be a bit screwed up
            # because we do not keep track of whether constraint_i_j
            # changed due to the intersection
            constraint_i_j.relset = intersection
            self._add_constraint_to_edge(constraint_i_j, edge_i_j)
            
            # get the nodes from the edge and add the nodes to each
            # others edges_in and edges_out attributes
            node_i = constraint_i_j.get_node1()
            node_j = constraint_i_j.get_node2()
            node_i.edges_out[constraint_i_j.node2] = edge_i_j
            node_j.edges_in[constraint_i_j.node1] = edge_i_j

            # node_k --> node_i --> node_j
            #debug(2, 'EDGES_IN   (' + ' '.join(node_i.edges_in.keys()) + ')')
            for edge_k_i in node_i.edges_in.values():
                self._check_k_i_j(edge_k_i, edge_i_j, node_i, node_j)

            # node_i --> node_j --> node_k
            #debug(2, 'EDGES_OUT  (' + ' '.join(node_j.edges_out.keys()) + ')')
            for edge_j_k in node_j.edges_out.values():
                self._check_i_j_k(edge_i_j, edge_j_k, node_i, node_j)


    def reduce(self):

        """Create a minimal graph, removing disjunctions, normalizing
        relations, removing all constraints that can be derived, and
        collapsing equivalence classes."""

        self.remove_node('ei1')
        debug = False
        filebase = 'data/graphs/' + self.file.rstrip('xml').lstrip('data/')
        if debug: self.pp("%s" % filebase + '01.html')
        self._remove_disjunctions()
        if debug: self.pp("%s" % filebase + '02.html')
        self._remove_derivable_relations()
        if debug: self.pp("%s" % filebase + '03.html')
        self._normalize_relations()
        if debug: self.pp("%s" % filebase + '04.html')
        self._collapse_equivalence_classes()

        
    def remove_node(self, id):

        """Remove a node from the graph. Involves removing the node from the
        nodes hash, removing the node's column and row in the edges
        array and removing the node from edges_in and edges_out
        attributes of other nodes."""

        node = self.nodes[id]
        # remove from other nodes
        for nodeid in node.edges_in.keys():
            del self.nodes[nodeid].edges_out[id]
        for nodeid in node.edges_out.keys():
            del self.nodes[nodeid].edges_in[id]
        # remove from nodes hash
        del self.nodes[id]
        # remove from edges hash
        for nodeid in self.edges.keys():
            del self.edges[nodeid][id]
        del self.edges[id]
            
        
    def _intersect_constraints(self, edge, constraint):

        """Intersect the constraint that was just derived to the one already
        on the edge. There are three cases. (1) The new constraint, if
        it is the one originally handed to the propagate() function,
        could introduce an inconsistency, this should be reported
        (***which is not done yet***). (2) The new constraint could be
        identical to the one already there and can be ignored. (3) The
        new constraint is more specifc than the already existing
        constraint. The method returns False in the first two cases
        and the intersection in the last case."""
        
        edge = self.edges[constraint.node1][constraint.node2]
        new_relset = constraint.relset
        existing_relset = edge.relset
        intersection = intersect_relations(new_relset, existing_relset)
        #debug(2, "INTERSECT  %s + %s  -->  {%s}" % \
        #      (constraint, edge.constraint, intersection))
        if intersection == '':
            #debug(3, "IGNORING   %s (inconsistency)" % constraint)
            return False
        elif new_relset == existing_relset:
            #debug(3, "IGNORING   %s (constraint already there)" % constraint)
            return False
        else:
            #debug(4, "NEW CONSTRAINT")
            return intersection


    def _check_k_i_j(self, edge_k_i, edge_i_j, node_i, node_j):

        """Look at the k->i->j subgraph and check whether the new constraint
        in Edge(i,j) allows you to derive something new by
        composition. The nodes node_i and node_j could be derived from
        edge_i_j but are handed to this function because they were
        already available and it saves a bit of time this way."""
        
        node_k = edge_k_i.get_node1()
        if node_k.id == node_j.id:
            return
        edge_k_j = self._get_edge(node_k, node_j)
        relset_k_j = self._compose(edge_k_i, edge_i_j.constraint)
        #debug(3, "COMPOSE    %s * %s --> {%s}  ||  %s " \
        #      % (edge_k_i.constraint, edge_i_j.constraint, relset_k_j, edge_k_j.constraint))
        if not relset_k_j == None:
            self._combine(edge_k_j, relset_k_j, edge_k_i.constraint, edge_i_j.constraint)


    def _check_i_j_k(self, edge_i_j, edge_j_k, node_i, node_j):

        """Look at the i->j->k subgraph and check whether the new constraint
        in Edge(i,j) allows you to derive something new by
        composition. The nodes node_i and node_j could be derived from
        edge_i_j but are handed to this function because they were
        already available and it saves a bit of time this way."""
        
        node_k = edge_j_k.get_node2()
        if node_k.id == node_i.id:
            return
        edge_i_k = self._get_edge(node_i, node_k)
        relset_i_k = self._compose(edge_i_j.constraint, edge_j_k)
        #debug(3, "COMPOSE    %s * %s --> {%s}  ||  %s " \
        #      % (edge_i_j.constraint, edge_j_k.constraint, relset_i_k, edge_i_k.constraint))
        if not relset_i_k == None:
            self._combine(edge_i_k, relset_i_k, edge_i_j.constraint, edge_j_k.constraint)

        
    def _combine(self, edge, relset, c1, c2):

        """Compare the relation set on the edge to the relation set created by
        composition. Creates the intersection of the relation sets and
        checks the result: (i) inconsistency, (ii) more specific than
        relation set on edge, or (iii) something else. The alrgument
        c1 and c2 are the constraints that were composed to create
        relset and will be used to set the history on a new constraint
        if it is created."""

        edge_relset = edge.relset
        intersection = intersect_relations(edge_relset, relset)
        if intersection == '':
            #debug(4, "WARNING: found an inconsistency where it shouldn't be")
            pass
        elif intersection == None:
            #debug(4, "WARNING: intersection is None, this should not happen")
            pass
        elif edge_relset == None:
            self._add_constraint_to_queue(edge, intersection, c1, c2)
        elif len(intersection) < len(edge_relset):
            self._add_constraint_to_queue(edge, intersection, c1, c2)
            
            
    def _add_constraint_to_queue(self, edge, relset, c1, c2):

        new_constraint = Constraint(edge.node1, relset, edge.node2)
        new_constraint.cycle = self.cycle
        new_constraint.source = 'closure' 
        new_constraint.history = (c1, c2)
        self.queue.append(new_constraint)
        #debug(4, "ADD QUEUE  %s " % new_constraint)

        add_inverted = True
        add_inverted = False
        # Adding the inverted constraint should not be needed, except
        # perhaps as a potential minor speed increase. As far I can
        # see however, the method is actually slower when adding the
        # inverse (about 20%), which is surprising. But the results
        # are the same.
        if add_inverted:
            relset = invert_interval_relations(relset)
            new_constraint2 = Constraint(edge.node2, relset, edge.node1)
            new_constraint.cycle = self.cycle
            new_constraint2.source = 'closure-inverted' 
            new_constraint2.history = new_constraint
            self.queue.append(new_constraint2)
            #debug(4, "ADD QUEUE  %s " % new_constraint2)

        
    def _compose(self, object1, object2):
        """Return the composition of the relation sets on the two objects. One
        object is an edge, the other a Constraint. Once the relations
        are retrieved from the objects all that's needed is a simple
        lookup in the compositions table."""
        rels1 = object1.relset
        rels2 = object2.relset
        return self.compositions.compose_rels(rels1, rels2)
    
    def _add_constraint_to_edge(self, constraint, edge):
        """This method links a constraints to its edge by retrieving the edge
        from the graph, adding the constraint to this edge, and
        setting the edge attribute on the constraint."""
        #edge = self.edges[constraint.node1][constraint.node2]
        edge.add_constraint(constraint)
        constraint.edge = edge

    def _OLD_get_edge(self, node1, node2):
        """Return the edge from node1 to node2."""
        # use edges_out of node1 (could also use edges_in of node2)
        edge =  node1.edges_out.get(node2.id, None)
        # use the edges table if there is no edge between the nodes
        if edge == None:
            edge = self.edges[node1.id][node2.id]
        return edge
    
    def _get_edge(self, node1, node2):
        """Return the edge from node1 to node2."""
        return self.edges[node1.id][node2.id]
    
    def get_edges(self):
        """Return all edges that have a constraint on them."""
        edges = []
        for n1 in self.edges.keys():
            for n2 in self.edges[n1].keys():
                edge = self.edges[n1][n2]
                if n1 != n2 and edge.constraint:
                    edges.append(edge)
        return edges
        
    def _remove_disjunctions(self):
        """Remove all disjunctions from the graph."""
        for edge in self.get_edges():
            if edge.constraint:
                if edge.constraint.is_disjunction():
                    edge.remove_constraint()
    
    def _normalize_relations(self):
        """Remove all relations that are not in the set of normalized
        relations."""
        for edge in self.get_edges():
            if edge.constraint:
                if not edge.constraint.has_normalized_relation():
                    edge.remove_constraint()            
    
    def _remove_derivable_relations(self):
        """First mark and then remove all constraints that can be derived."""
        for edge in self.get_edges():
            edge.remove = False
            if edge.is_derivable():
                edge.remove = True
        for edge in self.get_edges():
            if edge.remove:
                edge.remove_constraint()

    
    def _collapse_equivalence_classes(self):
        equal_edges = []
        for edge in self.get_edges():
            if edge.relset == '=':
                equal_edges.append(edge)
        #print equal_edges


    def pp_nodes(self):
        """Print all nodes with their edges_in and edges_out attributes to
        standard output."""
        ids = self.nodes.keys()
        ids.sort(compare_id)
        for id in ids:
            self.nodes[id].pretty_print()

            
    def pp(self, filename):

        """Print the graph to an HTML table in filename."""
        
        file = open(filename, 'w')
        
        file.write("<html>\n")
        file.write("<head>\n<style type=\"text/css\">\n<!--\n")
        file.write("body { font-size: 14pt }\n")
        file.write("table { font-size: 14pt }\n")
        file.write(".user { background-color: lightblue}\n")
        file.write(".closure { background-color: pink }\n")
        file.write(".inverted { background-color: lightyellow }\n")
        file.write(".nocell { background-color: lightgrey }\n")
        file.write("-->\n</style>\n</head>\n")
        file.write("<body>\n\n")
        file.write("<table cellpadding=3 cellspacing=0 border=1>\n")
        file.write("\n<tr>\n\n")
        file.write("  <td>&nbsp;\n\n")

        nodes = self.nodes.keys()
        nodes.sort(compare_id)

        for id in nodes:
            file.write("  <td>%s\n" % id)      

        for id1 in nodes:
            file.write("\n\n<tr align=center>\n\n")
            file.write("  <td align=left>%s\n" % id1)  
            for id2 in nodes:
                edge = self.edges[id1][id2]
                rel = edge.relset
                if rel == None:
                    rel = '&nbsp;'
                rel = abbreviate_convex_relation(rel)
                rel = str(rel).replace('<', '&lt;')
                rel = str(rel).replace('>', '&gt;')
                rel = str(rel).replace(' ', '&nbsp;')
                c = ''
                if edge.constraint:
                    if edge.constraint.source == 'user':
                        c = ' class="user"'
                    elif edge.constraint.source == 'closure':
                        c = ' class="closure"'
                    elif edge.constraint.source.endswith('inverted'):
                        c = ' class="inverted"'
                bgcolor = ''
                if id1 == id2:
                    c = ' class="nocell"'
                    rel = '&nbsp;'
                file.write("  <td width=25pt%s>%s\n" % (c, str(rel)))
        file.write("</table>\n</body>\n</html>\n\n")



def debug(indent=0, str=''):
    if DEBUG:
        print '  ' * indent, str
        
