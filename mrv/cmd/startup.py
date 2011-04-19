# -*- coding: utf-8 -*-
"""Contains routines to startup individual programs"""
__docformat__ = "restructuredtext"

import sys
import os


#{ IPython 

def ipython_apply_user_configuration():
	"""Run optional user scripts"""
	# try to load custom settings
	if "IMRV_CONFIG" in os.environ:
		filepath = os.environ[ "IMRV_CONFIG" ]
		try:
			execfile( filepath )
		except Exception:
			print "Failed to run configuration script"
	else:
		print "Set IMRV_CONFIG to point to python script doing additional setup"

def ipython_setup_mrv():
	"""Initialize MRV
	:return: True if it initializes maya, otherwise return False"""
	# configure MRV
	# as IPython is some sort of interactive mode, we load the user preferences
	for var in ( 	'MRV_STANDALONE_AUTOLOAD_PLUGINS', 
					'MRV_STANDALONE_INIT_OPTIONVARS', 
					'MRV_STANDALONE_RUN_USER_SETUP' ): 
		os.environ[var] = "1"
	# END env var loop
	
	# init maya - if possible
	try:
		import mrv.maya
		return True
	except (EnvironmentError, ImportError):
		print "Didn't initialize Maya"
		return False
	# END handle maya import
	

def ipython_setup(maya_support):
	"""Perform additional ipython initialization"""
	import IPython
	import logging
	
	# init logging
	logging.basicConfig(level=logging.INFO)
	
	if maya_support:
		# make default imports
		ip = IPython.ipapi.get()
		ip.ex("from mrv.maya.all import *")
		
		
		# prefetch methods for convenience
		import mrv.maya.nt.typ as typ
		typ.prefetchMFnMethods()
	# END handle maya

# } END initialization


#} END ipython

#{ Startup

def mrv(args, info, args_modifier=None):
	"""Prepare the environment to allow the operation of maya
	:param info: info module instance
	:param args_modifier: Function returning a possibly modified argument list. The passed 
		in argument list was parsed already to find and extract the maya version. 
		Signature: ``arglist func(arglist, maya_version, start_maya, info)
		If start_maya is True, the process to be started will be maya.bin, not the 
		python interpreter. If maya_version is 0, the process will continue execution
		within this python interpreter which is assured to have mrv facilities availble 
		which do not require maya.
		The last argument is the project's info module"""
	import mrv.cmd
	import mrv.cmd.base as cmdbase
	
	# handle special arguments
	config = [False, False, False]
	lrargs = list(args)
	for i, flag in enumerate((mrv.cmd.mrv_ui_flag,
							  mrv.cmd.mrv_mayapy_flag, 
							  mrv.cmd.mrv_nomaya_flag)):
		# intentionally don't cause an exception to be set - even if we catch
		# it, its still hanging around and could be picked up by others who 
		# explicitly query it
		if flag in lrargs:
			lrargs.remove(flag)
			config[i] = True
		#END handle removal
	# END for each flag to handle
	start_maya, mayapy_only, no_maya = config
	rargs = lrargs
	
	if no_maya and ( start_maya or mayapy_only ):
		raise EnvironmentError("If %s is specified, %s or %s may not be given as well" % (mrv.cmd.mrv_nomaya_flag, mrv.cmd.mrv_ui_flag, mrv.cmd.mrv_mayapy_flag))
	
	force_reuse_this_interpreter = False 
	if not no_maya:
		force_reuse_this_interpreter, maya_version, rargs = cmdbase.init_environment(rargs)
	else:
		maya_version = 0.0
	# EMD initialize maya if required
	
	if args_modifier is not None:
		rargs = list(args_modifier(tuple(rargs), maya_version, start_maya, info))
	else:
		rargs = list(rargs)
	# END handle arg list
	
	if no_maya or (force_reuse_this_interpreter and not start_maya):
		# parse the option ourselves, the optparse would throw on unknown opts
		# Abort parsing of our options on the first options we didn't understand
		# and interpret them as options belonging to the starting program
		remaining_args = rargs[:]
		eval_script = None
		module = None
		if len(rargs) > 1:
			arg = rargs[0]
			if arg == '-c':
				eval_script = rargs[1]
			elif arg == '-m':
				module = rargs[1]
			# END check options
			
			if eval_script or module:
				remaining_args = rargs[2:]
			# END cut off our options
		# END for each arg
		
		# overwrite our own sys.args with our parsed arguments
		arg0 = sys.argv[0]
		del(sys.argv[:])
		sys.argv.extend([arg0] + remaining_args)
		
		if eval_script:
			exec(eval_script)
		elif module:
			__import__(module)
		elif remaining_args and os.path.isfile(remaining_args[0]):
			# if the first remaining arg is a file, execute it - all other args will
			# be accessible too
			fpath = remaining_args[0]
			ext = os.path.splitext(fpath)[1]
			
			# remove the filename, it wouldn't be availble if this was a real 
			# interpreter either
			del(sys.argv[1:])
			remaining_args.pop(0)
			sys.argv.extend(remaining_args)
			
			# adjust important variables to fake a standalone start
			global __name__, __file__
			__file__ = fpath
			__name__ = '__main__'
			
			if ext == ".py":
				execfile(fpath)
			elif ext in ('.pyc', '.pyo'):
				import marshal
				# If we have a pyc/pyo file, we mimic the python interpreter implementation
				# to get a code object out of it.
				bytes = open(fpath, 'rb').read()
				# skip two longs: magic number and .py last modified date stamp
				# unmashal the code object
				code = marshal.loads(bytes[8:])
				exec code in globals()
			else:
				raise ValueError("Unsupported file format in %r" % fpath)
			# END 
			
		elif not sys.stdin.closed:
			# read everything until stdin is closed, and execute it
			eval_script = sys.stdin.read()
			exec(eval_script)
		else:
			# we actually never get here, but leave it just ... in case
			raise EnvironmentError("Please specify '-c CMD' or '-m MODULE', or provide a file to indicate which code to execute")
		# END handle flags
		
	else:
		if start_maya:
			cmdbase.exec_maya_binary(rargs, maya_version)
		else:
			cmdbase.exec_python_interpreter(rargs, maya_version, mayapy_only)
		# END handle process to start
	# END handle flags
	
def imrv():
	"""Get the main ipython system up and running"""
	maya_support = ipython_setup_mrv()

	# init ipython - needs to be available in your local python installation
	try: 
		import IPython
	except Exception, e:
		raise ImportError("Warning: Failed to load ipython - please install it for more convenient maya python interaction: %s" % str(e))
	# END exception handling
	
	ips = IPython.Shell.start()
	ipython_setup(maya_support)
	ipython_apply_user_configuration()
	ips.mainloop()

#} END startup

