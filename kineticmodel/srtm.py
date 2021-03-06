import numpy as np
import numpy.matlib as mat
from scipy.linalg import solve
from scipy.ndimage import gaussian_filter
from scipy.optimize import basinhopping, minimize_scalar
from kineticmodel import KineticModel
from kineticmodel import integrate as km_integrate

class SRTM_Zhou2003(KineticModel):
    '''
    Compute distribution volume ratio (DVR) and relative delivery (R1) kinetic
    parameters from dynamic PET data based on a simplified reference tissue
    model (SRTM). The nonlinear SRTM equations are linearized using integrals of
    time activity curves (TACs) of the reference and target tissues. Kinetic
    parameters are then estimated by weighted linear regression (WLR).
    If provided, the spatially smoothed TAC of the target region is used in
    the computation of DVR as part of the linear regression with spatial
    constraint (LRSC) approach.

    To obtain the R1 estimate that incorporates spatial smoothness based on
    LRSC, run refine_R1() after running fit().

    Reference:
    Zhou Y, Endres CJ, Brašić JR, Huang S-C, Wong DF.
    Linear regression with spatial constraint to generate parametric images of
    ligand-receptor dynamic PET studies with a simplified reference tissue model.
    Neuroimage. 2003;18:975–989.
    '''

    # This class will compute the following results:
    result_names = [ # estimated parameters
                    'BP',
                    'DVR',
                    'R1','k2','k2a',
                    'R1_lrsc','k2_lrsc','k2a_lrsc',
                    # model fit indicators
                    'noiseVar_eqDVR','noiseVar_eqR1']

    def fit(self, smoothTAC=None):
        '''
        Estimate parameters of the SRTM Zhou 2003 model.

        Args:
            smoothTAC (numpy.ndarray): optional. 1- or 2-D array, where each row
                corresponds to a (spatially) smoothed time activity curve
        '''
        if smoothTAC is not None:
            if smoothTAC.ndim==1:
                if not len(smoothTAC)==len(self.t):
                    raise ValueError('smoothTAC and t must have same length')
                # make smoothTAC into a row vector
                smoothTAC = smoothTAC[np.newaxis,:]
            elif smoothTAC.ndim==2:
                if not smoothTAC.shape==self.TAC.shape:
                    raise ValueError('smoothTAC and TAC must have same shape')
            else:
                raise ValueError('smoothTAC must be 1- or 2-dimensional')

        n = len(self.t)
        m = 3

        # Numerical integration of reference TAC
        intrefTAC = km_integrate(self.refTAC,self.t,self.startActivity)

        # Compute BP/DVR, R1, k2, k2a
        for k, TAC in enumerate(self.TAC):
            W = mat.diag(self.weights[k,:])

            # Numerical integration of target TAC
            intTAC = km_integrate(TAC,self.t,self.startActivity)

            # ----- Get DVR -----
            # Set up the weighted linear regression model
            # based on Eq. 9 in Zhou et al.
            # Per the recommendation in first paragraph on p. 979 of Zhou et al.,
            # smoothed TAC is used in the design matrix, if provided.
            if smoothTAC is None:
                X = np.column_stack((intrefTAC, self.refTAC, -TAC))
            else:
                X = np.column_stack((intrefTAC, self.refTAC, -smoothTAC[k,:].flatten()))

            y = intTAC
            try:
                b = solve(X.T @ W @ X, X.T @ W @ y)
                residual = y - X @ b
                # unbiased estimator of noise variance
                noiseVar_eqDVR = residual.T @ W @ residual / (n-m)

                DVR = b[0]
                #R1 = b[1] / b[2]
                #k2 = b[0] / b[2]
                BP = DVR - 1
            except:
                DVR = BP = noiseVar_eqDVR = 0

            # ----- Get R1 -----
            # Set up the weighted linear regression model
            # based on Eq. 8 in Zhou et al.
            #X = np.mat(np.column_stack((self.refTAC,intrefTAC,-intTAC)))
            X = np.column_stack((self.refTAC,intrefTAC,-intTAC))
            #y = np.mat(TAC).T
            y = TAC
            try:
                b = solve(X.T @ W @ X, X.T @ W @ y)
                residual = y - X @ b
                # unbiased estimator of noise variance
                noiseVar_eqR1 = residual.T @ W @ residual / (n-m)

                R1 = b[0]
                k2 = b[1]
                k2a = b[2]
            except:
                R1 = k2 = k2a = noiseVar_eqR1 = 0

            self.results['BP'][k] = BP
            self.results['DVR'][k] = DVR
            self.results['R1'][k] = R1
            self.results['k2'][k] = k2
            self.results['k2a'][k] = k2a

            self.results['noiseVar_eqDVR'][k] = noiseVar_eqDVR
            self.results['noiseVar_eqR1'][k] = noiseVar_eqR1

        return self

    def refine_R1(self, smoothR1, smoothk2, smoothk2a, h):
        '''
        Ridge regression to get better R1, k2, k2a estimates

        Args:
            smoothR1 (float): R1 value to drive the estimate toward
            smoothk2 (float): k2 value to drive the estimate toward
            smoothk2a (float): k2a value to drive the estimate toward
            h (numpy.ndarray): 1-D array consisting of the  diagonal elements
                               of the matrix used to compute the weighted norm
        '''

        if not smoothR1.ndim==smoothk2.ndim==smoothk2a.ndim==1:
            raise ValueError('smoothR1, smoothk2, smoothk2a must be 1-D')
        if not len(smoothR1)==len(smoothk2)==len(smoothk2a)==self.TAC.shape[0]:
            raise ValueError('Length of smoothR1, smoothk2, smoothk2a must be \
                             equal to the number of rows of TAC')
        if not h.ndim==2:
            raise ValueError('h must be 2-D')
        if not h.shape==(self.TAC.shape[0], 3):
            raise ValueError('Number of rows of h must equal the number of rows of TAC, \
                             and the number of columns of h must be 3')

        # Numerical integration of reference TAC
        intrefTAC = km_integrate(self.refTAC,self.t,self.startActivity)
        for k, TAC in enumerate(self.TAC):
            W = mat.diag(self.weights[k,:])

            # Numerical integration of target TAC
            intTAC = km_integrate(TAC,self.t,self.startActivity)

            # ----- Get R1 incorporating spatial constraint -----
            # Set up the ridge regression model
            # based on Eq. 11 in Zhou et al.
            #X = np.mat(np.column_stack((self.refTAC,intrefTAC,-intTAC)))
            X = np.column_stack((self.refTAC,intrefTAC,-intTAC))
            #y = np.mat(TAC).T
            y = TAC
            H = mat.diag(h[k,:])
            b_sc = np.array((smoothR1[k],smoothk2[k],smoothk2a[k])) #.reshape(-1,1)

            try:
                b = solve(X.T @ W @ X + H, X.T @ W @ y + H @ b_sc)

                R1_lrsc = b[0]
                k2_lrsc = b[1]
                k2a_lrsc = b[2]
            except:
                R1_lrsc = k2_lrsc = k2a_lrsc = 0

            self.results['R1_lrsc'][k] = R1_lrsc
            self.results['k2_lrsc'][k] = k2_lrsc
            self.results['k2a_lrsc'][k] = k2a_lrsc

        return self

class SRTM_Lammertsma1996(KineticModel):
    '''
    Compute binding potential (BP) and relative delivery (R1) kinetic parameters
    from dynamic PET data based on a simplified reference tissue model (SRTM).

    Reference:
    Lammertsma AA, Hume SP. Simplified reference tissue model for PET receptor
    studies. NeuroImage. 1996 Dec;4(3 Pt 1):153-8.
    '''

    # This class will compute the following results:
    result_names = [ # estimated parameters
                    'BP','R1','k2']#,
                    # model fit indicators
                    #'akaike']

    def fit(self):
        n = len(self.t)
        m = 4 # 3 model parameters + noise variance

        def make_srtm_est(startActivity):
            '''
            Wrapper to construct the SRTM TAC estimation function with a given
            startActivity.

            Args:
                startActivity (str): determines initial condition for integration.
                                     See integrate in kineticmodel.py

            Returns:
                srtm_est (function): function to compute fitted TAC given t,
                                     refTAC, BP, R1, k2
            '''

            def srtm_est(X, BPnd, R1, k2):
                '''
                Compute fitted TAC given t, refTAC, BP, R1, k2.

                Args:
                    X (tuple): first element is t, second element is intrefTAC
                    BPnd (float): binding potential
                    R1 (float): R1
                    k2 (float): k2

                Returns:
                    TAC_est (numpy.ndarray): 1-D array
                                             estimated time activity curve
                '''
                t, refTAC = X

                k2a = k2/(BPnd+1)
                # Convolution of reference TAC and exp(-k2a*t) = exp(-k2a*t) * Numerical integration of
                # refTAC(t)*exp(k2a*t).

                exp_k2a_t = np.exp(k2a*t)
                integrant = refTAC * exp_k2a_t
                conv = km_integrate(integrant,t,startActivity) / exp_k2a_t
                TAC_est = R1*refTAC + (k2-R1*k2a)*conv

                return TAC_est

            return srtm_est

        X = (self.t, self.refTAC)

        # upper bounds for kinetic parameters in optimization
        BP_upper, R1_upper, k2_upper = (20.,10.,2.)

        srtm_fun = make_srtm_est(self.startActivity)

        for k, TAC in enumerate(self.TAC):
            w = self.weights[k,:]
            def energy_fun(kineticparams):
                return np.sum(w * np.square(TAC - srtm_fun(X, *kineticparams)))

            minimizer_kwargs = dict(method="L-BFGS-B",
                                    bounds=[(0,BP_upper),
                                            (0, R1_upper),
                                            (0, k2_upper)])
            res = basinhopping(energy_fun, x0=np.array([1.,1.,0.1]),
                               minimizer_kwargs=minimizer_kwargs)

            self.results['BP'][k], \
            self.results['R1'][k], \
            self.results['k2'][k] = res.x

        return self

class SRTM_Gunn1997(KineticModel):
    '''
    Compute binding potential (BP) and relative delivery (R1) kinetic parameters
    from dynamic PET data based on a simplified reference tissue model (SRTM).

    Reference:
    Roger N. Gunn, Adriaan A. Lammertsma, Susan P. Hume, and Vincent J.
    Cunningham. Parametric imaging of ligand-receptor binding in PET using a
    simplified reference region model. NeuroImage 6, 279-287 (1997).
    '''
    result_names = ['BP','R1','k2']

    def fit(self):
        #print(self.TAC.shape)
        for k, TAC in enumerate(self.TAC):
            W = mat.diag(self.weights[k,:])
            #y = np.mat(TAC).T
            y = TAC

            def energy_fun(theta3):
                exp_theta3_t = np.exp(np.asscalar(theta3)*self.t)
                integrant = self.refTAC * exp_theta3_t
                conv = km_integrate(integrant,self.t,self.startActivity) / exp_theta3_t
                #X = np.mat(np.column_stack((self.refTAC, conv)))
                X = np.column_stack((self.refTAC, conv))
                #thetas = solve(X.T * W * X, X.T * W * y)
                thetas = solve(X.T @ W @ X, X.T @ W @ y)
                #residual = y - X * thetas
                residual = y - X @ thetas
                #rss = residual.T * W * residual
                rss = residual.T @ W @ residual
                return rss

            res = minimize_scalar(energy_fun, bounds=(0.06, 0.6),
                                  method='bounded', options=dict(xatol=1e-1))
            theta3 = np.asscalar(res.x)

            exp_theta3_t = np.exp(theta3*self.t)
            integrant = self.refTAC * exp_theta3_t
            conv = km_integrate(integrant,self.t,self.startActivity) / exp_theta3_t
            #X = np.mat(np.column_stack((self.refTAC, conv)))
            X = np.column_stack((self.refTAC, conv))
            #thetas = solve(X.T * W * X, X.T * W * y)
            thetas = solve(X.T @ W @ X, X.T @ W @ y)

            R1 = thetas[0]
            k2 = thetas[1] + R1*theta3
            BP = k2 / theta3 - 1

            self.results['BP'][k] = BP
            self.results['R1'][k] = R1
            self.results['k2'][k] = k2

        return self
