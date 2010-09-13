"""Components and component wrappers 

Base classes for Tarsqi components implemented in Python as well as
Python wrappers for all Tarsqi components.

"""

import os
import time
import re

from ttk_path import TTK_ROOT
from utilities import logger
from utilities import xml_utils

from docmodel.xml_parser import Parser
from components.common_modules.document import protectNode

from xml.parsers.expat import ExpatError


class TarsqiComponent:

    """Abstract class for the python components."""
    
    def process(self, infile, outfile):
        """Ask the component to process a file fragment. This is the method that is called
        from the component wrappers and it should be overwritten on all subclasses. An
        error is written to the log file if this method is ever executed."""
        logger.error("TarsqiComponent.process() not overridden")

    def pp_doctree(self, componentName):
        """Print the result of the document tree created by the converter utility. Assumes
        there is a doctree instance variable that contains a Document object."""

        print "\n--------- DOCUMENT TREE for %s ----------" % componentName
        self.doctree.pretty_print()

    def pp_xmldoc(self, componentName):
        """Print the XML document."""
        print "\n--------- XmlDocument for %s ----------" % componentName
        self.xmldoc.pretty_print()



class ComponentWrapper:

    """Abstract class that contains some common functionality for all tarsqi component
    wrappers. Each Tarsqi component has a Python ComponentWrapper. Wrappers are
    responsible for (i) extracting from the XML document those fragments that need to be
    processed, (ii) asking the component to process each fragment and (iii) inserting the
    processed fragments back into the XML document. The parsed XML document lives in the
    document instance variable and results are inserted into that same document. The
    wrapper does not know where the input and output files are. However, each wrapper does
    keep track of where the input and output fragments are for its component (in the
    DIR_DATA directory with fixed extensions).

    Instance variables for all subclasses of ComponentWrapper:

       tarsqi_instance - a Tarsqi instance
       tag - a string indicating the content tag used to create
             fragments
       document - the XML document of the input file
       fragments - a list of fragments
       trap_errors - True|False
       DIR_DATA - directory where fragments are written to

       component_name - string indicating the name of the wrapped
                        component
       CREATION_EXTENSION - extension of fragment that is the input to
                            the wrapped component
       RETRIEVAL_EXTENSION - extension of fragment that is the output
                             of the wrapped component
       TMP_EXTENSION - extension of intermediate files, if used

    The last four variables are instantiated by the __init__ methods defined on the
    subclasses of ComponentWrapper. In addition, those subclasses may initialise (1) a
    directory where the executables for the wrapped components are, which is needed for
    the non-Python components, and (2) an instance of the component parser."""
       
    # NOTES: 
    # - wrappers now use files as input and output, this may be changed
    #   to using in-memory strings to reduce disk operations
    # - may want to look at all the extension that are used, there may be
    #   some overlap.
    # - the tarsqi_instance vriable was added later, with it, we may
    #   want to get rid of some of the other ones

    
    def __init__(self, tag, xmldoc, tarsqi_instance):
        """Commonn initialization for all component wrappers. Initializes the
        tag, document, fragments, and DIR_DATA variables."""
        self.tarsqi_instance = tarsqi_instance
        self.tag = tag
        self.document = xmldoc
        self.fragments = []
        self.DIR_DATA = os.path.join(TTK_ROOT, 'data', 'tmp')


    def process(self):

        """This is the method that is called from the Tarsqi class. Fragments are created,
        processed and retrieved. The method that processes fragments (process_fragment)
        should be defined for each wrapper individually.

        No arguments and no return value."""

        self.create_fragments(self.tag, 'fragment')
        begin_time = time.time()
        self.process_fragments()
        end_time = time.time()
        total_time = end_time - begin_time
        logger.info("%s DONE, processing time was %.3f seconds" %
                    (self.component_name, total_time))
        self.retrieve_fragments('fragment')
        

    def create_fragments(self, tagname, wrapping_tag=None, remove_tags=False):

        """ Fragments are pairs of a file basename and a DocElement that contains an
        opening tag. The file basename points to a fragment file in the temporary data
        directory. The DocElement points to the tag in the document in which the fragment
        is contained and it can be used to update the content of that tag. The DocElement
        instance knows how to get the content between opening and closing tags. For each
        tag named 'tagname', the elements between the opening and closing tags are
        extracted and put in a separate fragment file.

        Arguments: 
           tagname -
              name of the tag that contains the fragments from input file that need to be
              processed
           wrapping_tag -
              name of the tag that is used to wrap the content of the fragment file
           remove_tags -
              a boolean that indicates whether tags are allowed to be removed from the
              content of the fragment if the remove_tags processing option is set to True;
              this only makes sense for the source file, in fact, if this parameter is set
              to True for any other component but the preprocessor, all tags including the
              ones generated by eg Evita will be removed

        Return value: None """

        # NOTE: should probably be defined in library.forms
        re_tag = re.compile('^</?([-\w]+).*>$')

        index = 0
        self.fragments = []

        for tag in self.document.tags[self.tag]:

            text_list = tag.collect_content_list()
            index = index + 1
            base = "fragment_%03d" % index
            self.fragments.append([base, tag])
            file_name = self.DIR_DATA + os.sep + base + '.' + self.CREATION_EXTENSION
            frag_file = open(file_name, "w")
            # add an XML root
            if wrapping_tag:
                frag_file.write("<%s>" % wrapping_tag)
            # write content strings from the list to the file, except
            # when the content is a tag and tags need to be removed
            for t in text_list:
                t = t.encode('ascii', 'replace')
                t = protectNode(t)
                if remove_tags and self.tarsqi_instance.getopt_remove_tags():
                    if t.startswith('<') and t.endswith('>'):
                        continue
                frag_file.write(t)
            # close XML root
            if wrapping_tag:
                frag_file.write("</%s>" % wrapping_tag)
            frag_file.close()


    def retrieve_fragments(self, wrapping_tag=None):

        """Retrieve fragments and insert them into the tags that the fragments were
        extracted from.

        Arguments:
           wrapping_tag - name of the tag (if any) that was used by create_fragments to
                          wrap the content of the fragment file, it needs to be removed in
                          this method

        Unlike with create_fragments, there is no tag argument. This argument is not
        needed here because a fragment is a pair of a file base name tag and a DocElement
        that contains the tag."""

        for fragment in self.fragments:
            (base, tag) = fragment
            filename = "%s/%s.%s" % (self.DIR_DATA, base, self.RETRIEVAL_EXTENSION)
            fh = open(filename, 'r')
            text = fh.read()
            try:
                doc = Parser().parse_string(text)
            except ExpatError:
                # try this in case input did not have a root element
                doc = Parser().parse_string('<fragment>'+text+'</fragment>')
                wrapping_tag = 'fragment'
            if wrapping_tag:
                # remove wrapping tag
                doc.elements.pop()
                doc.elements.pop(0)
            tag.replace_content_with_list(doc.elements)
