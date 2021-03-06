# -*- coding: utf-8 -*-
"""Contains basic classes and functionaliy"""
__docformat__ = "restructuredtext"
import os
import sys
import optparse
import subprocess
import shutil

import mrv
import mrv.doc

import mrv.test.cmd as cmd

from mrv.path import (make_path, Path)

ospd = os.path.dirname


__all__ = [ "DocGenerator" ]


class DocGenerator(object):
	"""Encapsulates all functionality required to create sphinx/epydoc documentaiton"""

	#{ Configuration 
	forbidden_dirs = ['test', 'ext', 'doc', '.']
	
	# PATHS
	source_dir = make_path('source')
	source_dl_dir = source_dir / 'download'
	
	build_dir = make_path('build')
	
	html_dir = build_dir / 'html'
	downloads_dir = html_dir / '_downloads'
	
	# EPYDOC
	epydoc_show_source = 'yes'
	epydoc_modules = """modules: unittest
modules: ../mrv,../mrv/ext/networkx/networkx,../mrv/ext/pyparsing/src,../mrv/ext/pydot"""

	epydoc_exclude = "mrv.test,mrv.cmd.ipythonstartup"

	# BOOTSTRAPPING
	# To be set by derived types in order to define the root package name that 
	# shouldbe imported
	package_name = None

	# DYNAMICALLY ADJUSTED MEMBERS
	# These members will be adjusted after reading the current project's 
	# information
	pinfo = None
	rootmodule = None
	epydoc_cfg = """[epydoc]
name: %s
url: %s

sourcecode: %s
%s

exclude: %s
output: html"""

	#} END configuration

	def __init__(self, sphinx=True, sphinx_autogen=True, coverage=True, epydoc=True, base_dir='.', *args):
		"""Initialize the instance
		
		:param sphinx: If True, sphinx documentation will be produced
		:param coverage: If True, the coverage report will be generated
		:param epydoc: If True, epydoc documentation will be generated"""
		if self.pinfo is None:
			self._retrieve_project_info(base_dir)
		# END asssure project info is set
		
		self._sphinx = sphinx
		self._sphinx_autogen = sphinx_autogen
		self._coverage = coverage
		self._epydoc = epydoc
		
		self._base_dir = make_path(base_dir)
		
		# We assume to be in the project's doc directory, otherwise we cannot
		# automatically handle the project information
		if self._base_dir.abspath().basename() != 'doc':
			raise EnvironmentError("Basedirectory needs to be the 'doc' directory, not %s" % self._base_dir.abspath())
			
		
		self._project_dir = make_path(self._base_dir / "..")
	
	@classmethod
	def _apply_epydoc_config(cls):
		"""Read package info configuration and apply it"""
		assert cls.pinfo is not None
		dcon = getattr(cls.pinfo, 'doc_config', dict())
		for k,v in dcon.items():
			if k.startswith('epydoc'):
				setattr(cls, k, v)
		# END apply project info 
		
		cls.epydoc_cfg = cls.epydoc_cfg % (cls.pinfo.project_name, 
											cls.pinfo.url, 
											cls.epydoc_show_source,
											cls.epydoc_modules, 
											cls.epydoc_exclude)
		
	
	#{ Public Interface
	
	@classmethod
	def remove_version_info(cls, idstring, basedir='.'):
		"""Remove the version info file if it exists"""
		try:
			os.remove(cls.version_file_name(idstring, basedir))
		except OSError:
			pass
		# END exception handling
	
	@classmethod
	def version_file_name(cls, idstring, basedir='.'):
		""":return: filename at which to write the version file with the given id"""
		return make_path(os.path.join(basedir, "%s.version_info" % idstring)) 

	@classmethod
	def write_version(cls, idstring, basedir='.'):
		"""Writes a version file containing the rootmodule's version info. 
		This allows to verify that the version of the individual parts, like
		epydoc and sphinx are still matching"""
		version_string = "version_info = (%i, %i, %i, '%s', %i)" % cls.pinfo.version
		open(cls.version_file_name(idstring, basedir), 'wb').write(version_string)
	
	@classmethod
	def check_version(cls, opid, idstring, basedir='.'):
		"""Checks whether the current version info matches with the stored version info
		as retrieved from idstring. 
		If there is no such info or if the version matches exactly, do nothing. 
		Otherwise raise an environment error to tell the user to rebuild the 
		respective part of the documentation"""
		vlocals = dict()
		vfile = cls.version_file_name(idstring, basedir)
		if not os.path.isfile(vfile):
			return
		
		execfile(vfile, vlocals)
		vinfo = vlocals['version_info']
		if vinfo != cls.pinfo.version:
			msg = "Documentation target named '%s' at version %s requires '%s' ( last built at %s ) to be rebuild" % (opid, str(cls.pinfo.version), idstring, str(vinfo))
			raise EnvironmentError(msg)
		# END raise exception
	
	@classmethod
	def parser(cls):
		""":return: OptionParser instance suitable to parse commandline arguments
		with which to initialize our instance"""
		usage = """%prog [options]
		
		Make documentation or remove the generated files."""
		parser = optparse.OptionParser(usage=usage)
		
		hlp = "Specify the name of the package to import, defaults to 'mrv'"
		parser.add_option('-p', '--package', dest='package_name', help=hlp)
		
		hlp = """Specifies to build sphinx documentation"""
		parser.add_option('-s', '--sphinx', dest='sphinx', type='int',default=1,
							help=hlp, metavar='STATE')
		
		hlp = """If specified, sphinx API docuementation will be generated"""
		parser.add_option('-a', '--sphinx-autogen', dest='sphinx_autogen', type='int', default=1, 
							help=hlp, metavar='STATE')
		
		hlp = """Specifies epydoc documentation"""
		parser.add_option('-e', '--epydoc', dest='epydoc', type='int', default=1, 
							help=hlp, metavar='STATE')
		
		hlp = """Specifies a coverage report. It will be referenced from within the 
		sphinx documentation"""
		parser.add_option('-c', '--coverage', dest='coverage', type='int', default=1, 
							help=hlp, metavar='STATE')
		
		return parser
		
	@classmethod
	def root_dir(cls, basedir='.'):
		"""
		:return: path which includes our package - if it would be in the sys.path, 
			we should be able to import it
		:param basedir: we expect to be in the root/doc path of the project - if this is not 
			the case, the basedir can be adjusted accordingly to 'virtually' chdir into the 
			doc directory"""
		return ospd(os.path.realpath(os.path.abspath(basedir)))
		
	@classmethod
	def makedoc(cls, args):
		"""Produce the actual docs using this type"""
		p = cls.parser()
		
		hlp = """If specified, previously generated files will be removed. Works in conjunction 
		with the other flags, which default to True, hence %prog --clean will remove all 
		generated files by default"""
		p.add_option('--clean', dest='clean', action='store_true', default=False, help=hlp)
		
		options, args = p.parse_args(args)
		clean = options.clean
		del(options.clean)
		
		# commandline overrides class configuration
		cls.package_name = options.package_name or cls.package_name
		# assume mrv, and assert it really is in our root path
		default_package = 'mrv'
		if cls.package_name is None and os.path.isdir(os.path.join(cls.root_dir(), default_package)):
			cls.package_name = default_package
		#END handle default
		
		if cls.package_name is None:
			p.error("Please specify the --package that should be imported")
		#END assure package is set
		del(options.package_name)
		
		dgen = cls(*args, **options.__dict__)
		if clean:
			dgen.clean()
		else:
			dgen.generate()
		# END handle mode
	
	def generate(self):
		"""Geneate the documentation according to our configuration
		
		:note: respects the options given during construction"""
		if self._coverage:
			self._make_coverage()
		
		if self._epydoc:
			self._make_epydoc()
		
		if self._sphinx:
			self._make_sphinx_index()
			if self._sphinx_autogen:
				self._make_sphinx_autogen()
			# END generate autogen
			self._make_sphinx()
		# END make sphinx
	
	def clean(self):
		"""Clean the generated files by removing them
		:note: Must respect the options the same way as done by the ``generate``
		method"""
		if self._coverage:
			self.remove_version_info('coverage')
			bdd = self.build_downloads_dir()
			csdd = self.source_downloads_coverage_dir()
			coverage_dir = make_path(self._project_dir / cmd.tmrv_coverage_dir)
			
			# delete all files we copied from the coverage dir
			if coverage_dir.isdir():
				for fpath in coverage_dir.files():
					tfpath = bdd / fpath.basename()
					if tfpath.isfile():
						tfpath.remove()
					# END remove file
				# END for each coverage file to remove
			# END if coverage directory exists
			
			try:
				shutil.rmtree(csdd)
			except OSError:
				pass
			# END exceptionhandlint
			
		# END clean coverage 
		
		if self._epydoc:
			self.remove_version_info('epydoc')
			try:
				shutil.rmtree(self.epydoc_target_dir())
			except OSError:
				pass
			# END ignore errors if directory doesnt exist
		# END clean epydoc
		
		if self._sphinx:
			self.remove_version_info('sphinx')
			ip = self.index_rst_path()
			iph = ip+'.header'
			# only remove index.rst if it appears we are generating it using 
			# header and footer
			if iph.isfile() and ip.isfile():
				ip.remove()
			# END remove generated index
			
			out_dir = self.html_output_dir()
			dt_dir = self.doctrees_dir()
			agp = self.autogen_output_dir()
			for dir in (agp, out_dir, dt_dir):
				if dir.isdir():
					shutil.rmtree(dir)
				# END remove html dir
			# END for each directory
		# END clean sphinx
	#} END public interface
	
	#{ Paths
	
	def base_dir(self):
		""":return: Path containing all documentation sources and output files"""
		return self._base_dir
		
	def set_base_dir(self, base_dir):
		"""Set the base directory to the given value
		:return: self"""
		self._base_dir = Path(base_dir)
		return self
		
	def index_rst_path(self):
		""":return: Path to index rst file"""
		return self._base_dir / self.source_dir / "index.rst"
		
	def build_downloads_dir(self):
		""":return: Path to the build downloads directory"""
		return self._base_dir / self.downloads_dir
		
	def source_downloads_dir(self):
		""":return: Path to the source downloads directory"""
		return self._base_dir / self.source_dl_dir
		
	def source_downloads_coverage_dir(self):
		""":return: Path to coverage related downloads"""
		return self.source_downloads_dir() / 'coverage'
		
	def epydoc_target_dir(self):
		""":return: Path to directory to which epydoc will write its output"""
		return self.html_output_dir() / 'generated' / 'api'
		
	def html_output_dir(self):
		""":return: html directory to receive all output"""
		return self._base_dir / self.html_dir
		
	def autogen_output_dir(self):
		""":return: directory to which sphinx-autogen will write its output to"""
		return self._base_dir / self.source_dir / 'generated'
		
	def doctrees_dir(self):
		""":return: Path to doctrees directory to which sphinx writes some files"""
		return self._base_dir / self.build_dir / 'doctrees'
	
	def mrv_bin_path(self):
		""":return: Path to mrv binary"""
		import mrv.cmd.base
		return mrv.cmd.base.find_mrv_script('mrv')
		
	def tmrv_bin_path(self):
		""":return: Path to tmrv binary"""
		import mrv.cmd.base
		return mrv.cmd.base.find_mrv_script('tmrv')
		
	#} END paths
	
	#{ Utilities
	def _mrv_maya_version(self):
		""":return: maya version with which mrv subcommands should be started with"""
		import mrv.cmd.base
		try:
			return mrv.cmd.base.available_maya_versions()[-1]
		except IndexError:
			print >> sys.stderr, "No maya version available, trying without"
			import mrv.cmd
			return mrv.cmd.mrv_nomaya_flag
		#END handle no maya available
		
	def _call_python_script(self, *args, **kwargs):
		"""Wrapper of subprocess.call which assumes that we call a python script.
		On windows, the python interpreter needs to be called directly
		:raise EnvironmentError: if the called had a non-0 return value"""
		if sys.platform.startswith('win'):
			args[0].insert(0, "python")
		# END handle windows
		cmd = ' '.join(str(i) for i in args[0])
		print cmd
		rval = subprocess.call(*args, **kwargs)
		
		if rval:
			raise EnvironmentError("Call to %s failed with status %i" % (args[0][0], rval))
		# END handle call error
	#} END utilities
	
	#{ Protected Interface
	
	@classmethod
	def _retrieve_project_info(cls, base_dir='.'):
		"""Store the project information of the actual project in our class members
		for later use
		:note: must be called exactly once"""
		if cls.pinfo is not None:
			return cls.pinfo
		#END handle cached pinfo
		
		if cls.package_name is None:
			raise ValueError("Package name needs to be set, but was None")
		#END assure package is set
		
		# Even though we could use the mrv.pinfo module, which is the top-level
		# package info, we should prefer to start a search based on our current 
		# directory as the user must call us from his own doc-path, from which 
		# we can conclude quite a lot
		rootpath = cls.root_dir(base_dir)
		sys.path.append(rootpath)
		
		try:
			cls.rootmodule = __import__(cls.package_name)
		except ImportError:
			raise EnvironmentError("Root package %s could not be imported" % cls.package_name)
		# END handle import
		
		pinfo_package =  "%s.info" % cls.package_name
		try:
			cls.pinfo = __import__(pinfo_package, fromlist=[''])
		except ImportError:
			raise EnvironmentError("Project information module %r could not be imported:" % pinfo_package)
		# END handle import


	def _make_sphinx_index(self):
		"""Generate the index.rst file according to the modules and packages we
		actually have"""
		import mrv
		
		indexpath = self.index_rst_path()
		index_header = indexpath+'.header'
		if not index_header.isfile():
			return
		# END handle header doesn't exist
		
		ifp = open(indexpath, 'wb')
		# write header
		ifp.write(index_header.bytes())
		
		# write api index
		if self._sphinx_autogen:
			basepath = self._base_dir / ".." / self.pinfo.root_package
			rootmodule = basepath.abspath().basename()
			for root, dirs, files in os.walk(basepath):
				remove_dirs = list()
				for dirname in dirs:
					if dirname in self.forbidden_dirs:
						remove_dirs.append(dirname)
					# END for each forbidden dir
				# END for each directory
				
				for dirname in remove_dirs:
					del(dirs[dirs.index(dirname)])
				# END for each dirname to remove
				
				for fname in files:
					if not fname.endswith('.py') or fname.startswith('_'):
						continue
					filepath = os.path.join(root, fname)
					
					# + 1 as there is a trailing path separator
					modulepath = "%s.%s" % (rootmodule, filepath[len(basepath)+1:-3].replace(os.path.sep, '.'))
					ifp.write("\t%s\n" % modulepath)
				# END for each file
			# END for each file
		# END generate api index 
		
		# finalize it, write the footer
		ifp.write((indexpath+'.footer').bytes())
		ifp.close()
	
	def _make_coverage(self):
		"""Generate a coverage report and make it available as download"""
		tmrvpath = self.tmrv_bin_path()
		
		# for some reason, the html output can only be generated if the current 
		# working dir is in the project root. Its something within nose's coverage 
		# module apparently
		prevcwd = os.getcwd()
		os.chdir(self._project_dir)
		
		try:
			rval = self._call_python_script([tmrvpath, str(self._mrv_maya_version()), 
											"%s=%s" % (cmd.tmrv_coverage_flag, self.pinfo.root_package)])
		finally:
			os.chdir(prevcwd)
		# END handle cwd
		
		if rval:
			raise SystemError("tmrv reported failure")
		# END handle return value
		
		bdd = self.build_downloads_dir()
		csdd = self.source_downloads_coverage_dir()
		for dir in (bdd, csdd):
			if not dir.isdir():
				dir.makedirs()
			# END if dir doesnt exist, create it
		# END for each directory 
		
		# coverage was generated into the current working dir
		# index goes to downloads in the source directory as it is referenced
		# by the docs
		coverage_dir = make_path(self._project_dir / cmd.tmrv_coverage_dir)
		cindex = coverage_dir / 'index.html'
		shutil.copy(cindex, csdd)
		
		# all coverage html files go to the downlods directory
		for html in coverage_dir.files():
			shutil.copy(html, bdd)
		# END for each html
		
		self.write_version('coverage')
		
		
	def _make_sphinx_autogen(self):
		"""Instruct sphinx to generate the autogen rst files"""
		# will have to run it in a separate process for maya support
		mrvpath = self.mrv_bin_path()
		
		# note: the mrv import resolves the site-packages for us which does not
		# happen on osx for some reason
		code = "import mrv; import sphinx.ext.autosummary.generate as sas; sas.main()"
		agp = self.autogen_output_dir()
		
		# make sure its clean, otherwise we will reprocess the same files
		if agp.isdir():
			shutil.rmtree(agp)
			agp.makedirs()
		# END handle existing directory
		
		# make sure the instance will actually find our info file, and not 
		# its own one, otherwise it cannot make the necessary imports
		os.environ['MRV_INFO_DIR'] = os.path.dirname(self.pinfo.__file__)
		args = [mrvpath, str(self._mrv_maya_version()), '-c', code, 
				'-o', agp, 
				self.index_rst_path()]
		
		self._call_python_script(args)
		
		# it could be that there was absolutely no autogenerated part in the 
		# index, hence it didn't write any rst files for it
		if not agp.isdir():
			print >> sys.stderr, "WARNING: No autogenerated rst files written to %s" % agp.abspath()
			return
		#END handle no autogen docs
		
		# POST PROCESS
		##############
		# Add :api:module.name which gets picked up by extapi, inserting a 
		# epydoc link to the respective file.
		for rstfile in agp.files("*.rst"):
			# insert module link
			lines = rstfile.lines()
			modulename = lines[0][6:-2]	# skip `\n
			lines.insert(2, ":api:`%s`\n" % modulename)
			
			# insert :api: links to the autoclasses
			i = 0
			l = len(lines)
			while i < l:
				line = lines[i]
				if line.startswith('.. autoclass'):
					classname = line[line.rfind(' ')+1:-1]	# skip newline
					l += 1
					lines.insert(i, ':api:`%s.%s`\n\n' % (modulename, classname))
					i += 1
				# END if we have a class
				i += 1
			# END for each line
			
			rstfile.write_lines(lines)
		# END for each rst to process
		
	def _sphinx_args(self):
		""":return: list of arguments to be used when calling sphinx from the commandline
		:note: directories of all kinds will be handled by the caller"""
		# we don't need "" around the values as we don't use a shell
		return ['-c', 'import sys, mrv, sphinx.cmdline; sphinx.cmdline.main(sys.argv)',
				'-b', 'html',
				'-D', 'latex_paper_size=a4', 
				'-D', 'latex_paper_size=letter',
				'-D', 'project=%s' % self.pinfo.project_name,
				'-D', 'copyright=%s' % self.pinfo.author,
				'-D', 'version=%s' % "%i.%i" % self.pinfo.version[:2],
				'-D', 'release=%s' % "%i.%i.%i-%s" % self.pinfo.version[:4]]
		
	def _make_sphinx(self):
		"""Generate the sphinx documentation"""
		self.check_version('sphinx', 'epydoc')
		self.check_version('sphinx', 'coverage')
		
		mrvpath = self.mrv_bin_path()
		out_dir = self.html_output_dir()
		
		for dir in (self.source_dir, out_dir):
			if not dir.isdir():
				dir.makedirs()
			# END assure directory exists
		# END for each directory
		
		pathargs = ['-d', self.doctrees_dir(), self.source_dir,  out_dir]
		
		args = [mrvpath, str(self._mrv_maya_version())] + self._sphinx_args() + pathargs 
				
		self._call_python_script(args)
		
		self.write_version('sphinx')
		
	def _make_epydoc(self):
		"""Generate epydoc documentation"""
		try:
			import epydoc
		except ImportError:
			raise ImportError("Epydoc could not be imported, please make sure it is available in your PYTHONPATH")
		#END handle epydoc installation
		
		self._apply_epydoc_config()
		
		# start epydocs in a separate process
		# as maya support is required
		epytarget = self.epydoc_target_dir()
		if not epytarget.isdir():
			epytarget.makedirs()
		# END assure directory exists
		
		# SETUP MONKEYPATCH
		def visit_paragraph(this, node):
			"""Epydoc patch - will be applied on demand"""
			if this.summary is not None:
				# found a paragraph after the first one
				this.other_docs = True
				raise docutils.nodes.NodeFound('Found summary')
		
			summary_pieces = []
		
			# Extract the first sentence.
			for child in node:
				if isinstance(child, docutils.nodes.Text):
					m = this._SUMMARY_RE.match(child)
					if m:
						summary_pieces.append(docutils.nodes.Text(m.group(1)))
						other = child[m.end():]
						if other and not other.isspace():
							this.other_docs = True
						break
				summary_pieces.append(child)
		
			summary_doc = this.document.copy() # shallow copy
			summary_para = node.copy() # shallow copy
			summary_doc[:] = [summary_para]
			summary_para[:] = summary_pieces
			this.summary = ParsedRstDocstring(summary_doc)
		#END monkaypatch method
		
		# write epydoc.cfg file temporarily
		epydoc_cfg_file = "epydoc.cfg"
		open(epydoc_cfg_file, 'wb').write(self.epydoc_cfg)
		
		args = ['epydoc', '-q', '-q', '--debug', '--config', epydoc_cfg_file, '-o', str(epytarget)]
		
		print "Launching in-process epydoc: ", " ".join(args)
		origargs = sys.argv[:]
		del(sys.argv[:])
		sys.argv.extend(args)
		try:
			try:
				# apply patch
				import docutils.nodes
				import epydoc.markup.restructuredtext
				from epydoc.markup.restructuredtext import ParsedRstDocstring
				epydoc.markup.restructuredtext._SummaryExtractor.visit_paragraph = visit_paragraph
				
				import epydoc.cli
				epydoc.cli.cli()
			except:
				import pdb
				print >> sys.stderr, "Epydoc encountered an exception - use pdb to figure out which code it couldn't handle"
				pdb.post_mortem(sys.exc_info()[-1])
				raise
			#END ease debugging
		finally:
			os.remove(epydoc_cfg_file)
			del(sys.argv[:])
			sys.argv.extend(origargs)
		# END handle epydoc config file
		
		self.write_version('epydoc')

	#} END protected interface

