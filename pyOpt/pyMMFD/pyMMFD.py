#!/usr/bin/env python
'''
pyMMFD - A Python pyOpt interface to MMFD (part of NASA's ADS). 

Copyright (c) 2008-2014 by pyOpt Developers
All rights reserved.
Revision: 1.2   $Date: 21/06/2010 21:00$


Tested on:
---------
Win32 with gfortran
Linux with pathf95

Developers:
-----------
- Dr. Ruben E. Perez (RP)
- Mr. Peter Jansen (PJ)

History
-------
	v. 1.0	- Initial Class Creation (RP, 2010)
	v. 1.1	- History support (PJ,RP, 2010)
	v. 1.2  - Gradient Class Support (PJ,RP, 2010)
'''

__version__ = '$Revision: $'

'''
To Do:
	- Include IOUT
	- Implement Informs
	- add unconstrained problems support
'''

# =============================================================================
# MMFD Library
# =============================================================================
try:
	import mmfd
except:
	raise ImportError('MMFD shared library failed to import')
#end

# =============================================================================
# Standard Python modules
# =============================================================================
import os, sys
import copy, time

# =============================================================================
# External Python modules
# =============================================================================
import numpy

# =============================================================================
# Extension modules
# =============================================================================
from pyOpt import Optimizer
from pyOpt import Gradient

# =============================================================================
# Misc Definitions
# =============================================================================
inf = 10.E+20  # define a value for infinity
# =============================================================================
eps = 1.0	# define a value for machine precision
while ((eps/2.0 + 1.0) > 1.0):
	eps = eps/2.0
#end
eps = 2.0*eps
#eps = math.ldexp(1,-52)


# =============================================================================
# MMFD Optimizer Class
# =============================================================================
class MMFD(Optimizer):
	
	'''
	MMFD Optimizer Class - Inherited from Optimizer Abstract Class
	'''
	
	def __init__(self, pll_type=None, *args, **kwargs):
		
		'''
		MMFD Optimizer Class Initialization
		
		**Keyword arguments:**
		
		- pll_type -> STR: Parallel Implementation (None, 'POA'-Parallel Objective Analysis), *Default* = None
		
		Documentation last updated:  Feb. 16, 2010 - Peter W. Jansen
		'''
		
		#
		if (pll_type == None):
			self.poa = False
		elif (pll_type.upper() == 'POA'):
			self.poa = True
		else:
			raise ValueError("pll_type must be either None or 'POA'")
		#end
		
		#
		name = 'MMFD'
		category = 'Local Optimizer'
		def_opts = {
		'IOPT':[int,0],           	# Feasible Directions Approach (0 - MMFD, 1 - MFD)
		'IONED':[int,0],          	# One-Dimensional Search Method (0,1,2,3)
		'CT':[float,-3e-2],       	# Constraint Tolerance
		'CTMIN':[float,4e-3],     	# Active Constraint Tolerance
		'DABOBJ':[float,1e-3],    	# Objective Absolute Tolerance (DABOBJ*abs(f(x)))
		'DELOBJ':[float,1e-3],    	# Objective Relative Tolerance
		'THETAZ':[float,1e-1],    	# Push-Off Factor
		'PMLT':[float,1e1],       	# Penalty multiplier for equality constraints
		'ITMAX':[int,4e2],        	# Maximum Number of Iterations
		'ITRMOP':[int,3],         	# consecutive Iterations Iterations for Convergence
		'IPRINT':[int,2],         	# Print Control (0 - None, 1 - Final, 2 - Iters)
		'IFILE':[str,'MMFD.out'],	# Output File Name
		}
		informs = {
		}
		Optimizer.__init__(self, name, category, def_opts, informs, *args, **kwargs)
		
		
	def __solve__(self, opt_problem={}, sens_type='FD', store_sol=True, store_hst=False, hot_start=False, disp_opts=False, sens_mode='', sens_step={}, *args, **kwargs):
		
		'''
		Run Optimizer (Optimize Routine)
		
		**Keyword arguments:**
		
		- opt_problem -> INST: Optimization instance
		- sens_type -> STR/FUNC: Gradient type, *Default* = 'FD' 
		- store_sol -> BOOL: Store solution in Optimization class flag, *Default* = True 
		- disp_opts -> BOOL: Flag to display options in solution text, *Default* = False
		- store_hst -> BOOL/STR: Flag/filename to store optimization history, *Default* = False
		- hot_start -> BOOL/STR: Flag/filename to read optimization history, *Default* = False
		- sens_mode -> STR: Flag for parallel gradient calculation, *Default* = ''
		- sens_step -> FLOAT: Sensitivity setp size, *Default* = {} [corresponds to 1e-6 (FD), 1e-20(CS)]
		
		Additional arguments and keyword arguments are passed to the objective function call.
		
		Documentation last updated:  February. 2, 2011 - Ruben E. Perez
		'''
		
		# 
		if ((self.poa) and (sens_mode.lower() == 'pgc')):
			raise NotImplementedError("pyMMFD - Current implementation only allows single level parallelization, either 'POA' or 'pgc'")
		#end
		
		if self.poa or (sens_mode.lower() == 'pgc'):
			try:
				import mpi4py
				from mpi4py import MPI
			except ImportError:
				print('pyMMFD: Parallel objective Function Analysis requires mpi4py')
			#end
			comm = MPI.COMM_WORLD
			nproc = comm.Get_size()
			if (mpi4py.__version__[0] == '0'):
				Bcast = comm.Bcast
			elif (mpi4py.__version__[0] == '1'):
				Bcast = comm.bcast
			#end
			self.pll = True
			self.myrank = comm.Get_rank()
		else:
			self.pll = False
			self.myrank = 0
		#end
		
		myrank = self.myrank
		
		# 
		def_fname = self.options['IFILE'][1].split('.')[0]
		hos_file, log_file, tmp_file = self._setHistory(opt_problem.name, store_hst, hot_start, def_fname)
		
		# 
		gradient = Gradient(opt_problem, sens_type, sens_mode, sens_step, *args, **kwargs)
		
		
		#======================================================================
		# MMFD - Objective/Constraint Values Function
		#======================================================================
		def mmfdfun(nv,nc,x,f,g):
			
			# Variables Groups Handling
			if opt_problem.use_groups:
				xg = {}
				for group in list(group_ids.keys()):
					if (group_ids[group][1]-group_ids[group][0] == 1):
						xg[group] = x[group_ids[group][0]]
					else:
						xg[group] = x[group_ids[group][0]:group_ids[group][1]]
					#end
				#end
				xn = xg
			else:
				xn = x
			#end
			
			# Flush Output Files
			self.flushFiles()
			
			# Evaluate User Function
			fail = 0
			ff = []
			gg = []
			if (myrank == 0):
				if self.h_start:
					[vals,hist_end] = hos_file.read(ident=['obj', 'con', 'fail'])
					if hist_end:
						self.h_start = False
						hos_file.close()
					else:
						[ff,gg,fail] = [vals['obj'][0][0],vals['con'][0],int(vals['fail'][0][0])]
					#end
				#end
			#end
			
			if self.pll:
				self.h_start = Bcast(self.h_start,root=0)
			#end
			if self.h_start and self.pll:
				[ff,gg,fail] = Bcast([ff,gg,fail],root=0)
			elif not self.h_start:	
				[ff,gg,fail] = opt_problem.obj_fun(xn, *args, **kwargs)
			#end
			
			# Store History
			if (myrank == 0):
				if self.sto_hst:
					log_file.write(x,'x')
					log_file.write(ff,'obj')
					log_file.write(gg,'con')
					log_file.write(fail,'fail')
				#end
			#end
			
			# Objective Assigment
			if isinstance(ff,complex):
				f = ff.astype(float)
			else:
				f = ff
			#end
			
			# Constraints Assigment
			for i in range(len(list(opt_problem._constraints.keys()))):
				if isinstance(gg[i],complex):
					g[i] = gg[i].astype(float)
				else:
					g[i] = gg[i]
				#end
			#end
			
			return f,g
		
		
		#======================================================================
		# MMFD - Objective/Constraint Gradients Function
		#======================================================================
		def mmfdgrd(nv,nc,x,f,g,df,dg):
			
			if self.h_start:
				dff = []
				dgg = []
				if (myrank == 0):
					[vals,hist_end] = hos_file.read(ident=['grad_obj','grad_con'])
					if hist_end:
						self.h_start = False
						hos_file.close()
					else:
						dff = vals['grad_obj'][0].reshape((len(list(opt_problem._objectives.keys())),len(list(opt_problem._variables.keys()))))
						dgg = vals['grad_con'][0].reshape((len(list(opt_problem._constraints.keys())),len(list(opt_problem._variables.keys()))))	
					#end
				#end
				if self.pll:
					self.h_start = Bcast(self.h_start,root=0)
				#end
				if self.h_start and self.pll:
					[dff,dgg] = Bcast([dff,dgg],root=0)
				#end
			#end
			
			if not self.h_start:
				
				# 
				dff,dgg = gradient.getGrad(x, group_ids, [f], g, *args, **kwargs)
				
			#end
			
			# Store History
			if self.sto_hst and (myrank == 0):
				log_file.write(dff,'grad_obj')
				log_file.write(dgg,'grad_con')
			#end
			
			# Gradient Assignment
			for i in range(len(list(opt_problem._variables.keys()))):
				df[i] = dff[0,i]
				for j in range(len(list(opt_problem._constraints.keys()))):
					dg[i,j] = dgg[j,i]
				#end
			#end
			
			return df,dg
		
		
		
		# Variables Handling
		nvar = len(list(opt_problem._variables.keys()))
		xl = []
		xu = []
		xx = []
		for key in list(opt_problem._variables.keys()):
			if (opt_problem._variables[key].type == 'c'):
				xl.append(opt_problem._variables[key].lower)
				xu.append(opt_problem._variables[key].upper)
				xx.append(opt_problem._variables[key].value)
			elif (opt_problem._variables[key].type == 'i'):
				raise IOError('MMFD cannot handle integer design variables')
			elif (opt_problem._variables[key].type == 'd'):
				raise IOError('MMFD cannot handle discrete design variables')
			#end
		#end
		xl = numpy.array(xl)
		xu = numpy.array(xu)
		xx = numpy.array(xx)
		
		# Variables Groups Handling
		group_ids = {}
		if opt_problem.use_groups:
			k = 0
			for key in list(opt_problem._vargroups.keys()):
				group_len = len(opt_problem._vargroups[key]['ids'])
				group_ids[opt_problem._vargroups[key]['name']] = [k,k+group_len]
				k += group_len
			#end
		#end
		
		# Constraints Handling
		ncon = len(list(opt_problem._constraints.keys()))
		neqc = 0
		gg = []
		idg = []
		if ncon > 0:
			for key in list(opt_problem._constraints.keys()):
				if opt_problem._constraints[key].type == 'i':
					idg.append(1)
				elif opt_problem._constraints[key].type == 'e':
					idg.append(-1)
				#end
				gg.append(opt_problem._constraints[key].value)
			#end
		else:
			raise IOError('MMFD support for unconstrained problems not implemented yet')
		#end
		gg = numpy.array(gg)
		idg = numpy.array(idg, numpy.int)
		
		# Objective Handling
		objfunc = opt_problem.obj_fun
		nobj = len(list(opt_problem._objectives.keys()))
		ff = []
		for key in list(opt_problem._objectives.keys()):
			ff.append(opt_problem._objectives[key].value)
		#end
		ff = numpy.array(ff)
		
		
		# Setup argument list values
		ndv = numpy.array([nvar], numpy.int)
		ncn = numpy.array([ncon], numpy.int) 
		if (self.options['IOPT'][1]>=0 and self.options['IOPT'][1]<=1):
			iopt = numpy.array([self.options['IOPT'][1]], numpy.int)
		else:
			raise IOError('Incorrect Feasible Directions Approach')
		#end
		if (self.options['IONED'][1]>=0 and self.options['IONED'][1]<=3):
			ioned = numpy.array([self.options['IONED'][1]], numpy.int)
		else:
			raise IOError('Incorrect One-Dimensional Search Method')
		#end
		if (myrank == 0):
			if (self.options['IPRINT'][1]>=0 and self.options['IPRINT'][1]<=2):
				iprint = numpy.array([self.options['IPRINT'][1]], numpy.int)
			else:
				raise IOError('Incorrect Output Level Setting')
			#end
		else:
			iprint = numpy.array([0], numpy.int)
		#end
		#iout = numpy.array([self.options['IOUT'][1]], numpy.int)
		ifile = self.options['IFILE'][1]
		if (iprint > 0):
			if os.path.isfile(ifile):
				os.remove(ifile)
			#end
		#end
		ct = numpy.array([self.options['CT'][1]], numpy.float)
		ctmin = numpy.array([self.options['CTMIN'][1]], numpy.float)
		
		finit,ginit = mmfdfun([],[],xx,ff,gg)
		dabobj = numpy.array([self.options['DABOBJ'][1]*finit], numpy.float)
		
		delobj = numpy.array([self.options['DELOBJ'][1]], numpy.float)
		thetaz = numpy.array([self.options['THETAZ'][1]], numpy.float)
		pmlt = numpy.array([self.options['PMLT'][1]], numpy.float)
		itmax = numpy.array([self.options['ITMAX'][1]], numpy.int)
		itrmop = numpy.array([self.options['ITRMOP'][1]], numpy.int)
		nrwk0 = 500
		nrwk1 = 10*(2*nvar+ncon) 
		nrwk2 = (ncon+2*nvar+3) 
		nrwk3 = (ncon+2*nvar)*((ncon+2*nvar)/2+1)
		nrwkS = nrwk0 + nrwk1 + nrwk2 + nrwk3
		nrwk = numpy.array([nrwkS], numpy.int)
		wk = numpy.zeros([nrwk], numpy.float)
		nriwk = numpy.array([nrwkS], numpy.int)
		iwk = numpy.zeros([nriwk], numpy.int)
		
		nfun = numpy.array([0], numpy.int)
		ngrd = numpy.array([0], numpy.int)
		
		
		# Run MMFD
		t0 = time.time()
		mmfd.mmfd(iopt,ioned,iprint,ndv,ncn,xx,xl,xu,ff,gg,idg,
			wk,nrwk,iwk,nriwk,ifile,ct,ctmin,dabobj,delobj,thetaz,
			pmlt,itmax,itrmop,nfun,ngrd,mmfdfun,mmfdgrd)
		sol_time = time.time() - t0
		
		if (myrank == 0):
			if self.sto_hst:
				log_file.close()
				if tmp_file:
					hos_file.close()
					name = hos_file.filename
					os.remove(name+'.cue')
					os.remove(name+'.bin')
					os.rename(name+'_tmp.cue',name+'.cue')
					os.rename(name+'_tmp.bin',name+'.bin')
				#end
			#end		
		#end
		
		if (iprint > 0):
		#	mmfd.closeunit(self.options['IOUT'][1])
			mmfd.closeunit(6)
		#end
		
		
		# Store Results
		sol_inform = {}
		sol_inform['value'] = []
		sol_inform['text'] = {}
		
		if store_sol:
			
			sol_name = 'MMFD Solution to ' + opt_problem.name
			
			sol_options = copy.copy(self.options)
			if 'defaults' in sol_options:
				del sol_options['defaults']
			#end
			
			sol_evals = nfun[0] + ngrd[0]*nvar
			
			sol_vars = copy.deepcopy(opt_problem._variables)
			i = 0
			for key in list(sol_vars.keys()):
				sol_vars[key].value = xx[i]
				i += 1
			#end
			
			sol_objs = copy.deepcopy(opt_problem._objectives)
			i = 0
			for key in list(sol_objs.keys()):
				sol_objs[key].value = ff[i]
				i += 1
			#end
			
			if ncon > 0:
				sol_cons = copy.deepcopy(opt_problem._constraints)
				i = 0
				for key in list(sol_cons.keys()):
					sol_cons[key].value = gg[i]
					i += 1
				#end
			else:
				sol_cons = {}
			#end
			
			sol_lambda = {}
			
			
			opt_problem.addSol(self.__class__.__name__, sol_name, objfunc, sol_time, 
				sol_evals, sol_inform, sol_vars, sol_objs, sol_cons, sol_options, 
				display_opts=disp_opts, Lambda=sol_lambda, Sensitivities=sens_type, 
				myrank=myrank, arguments=args, **kwargs)
			
		#end
		
		return ff, xx, sol_inform
		
		
		
	def _on_setOption(self, name, value):
		
		'''
		Set Optimizer Option Value (Optimizer Specific Routine)
		
		Documentation last updated:  May. 07, 2008 - Ruben E. Perez
		'''
		
		pass
		
		
	def _on_getOption(self, name):
		
		'''
		Get Optimizer Option Value (Optimizer Specific Routine)
		
		Documentation last updated:  May. 07, 2008 - Ruben E. Perez
		'''
		
		pass
		
		
	def _on_getInform(self, infocode):
		
		'''
		Get Optimizer Result Information (Optimizer Specific Routine)
		
		Keyword arguments:
		-----------------
		id -> STRING: Option Name
		
		Documentation last updated:  May. 07, 2008 - Ruben E. Perez
		'''
		
		pass
		
		
	def _on_flushFiles(self):
		
		'''
		Flush the Output Files (Optimizer Specific Routine)
		
		Documentation last updated:  August. 09, 2009 - Ruben E. Perez
		'''
		
		# 
		iPrint = self.options['IPRINT'][1]
		if (iPrint > 0):
			#mmfd.pyflush(self.options['IOUT'][1])
			mmfd.pyflush(6)
		#end
	


#==============================================================================
# MMFD Optimizer Test
#==============================================================================
if __name__ == '__main__':
	
	# Test MMFD
	print('Testing ...')
	MMFD = MMFD()
	print(MMFD)
	
