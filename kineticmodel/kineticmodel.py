from abc import ABCMeta, abstractmethod
from scipy import integrate as sp_integrate
import numpy as np
import warnings

class KineticModel(metaclass=ABCMeta):
    '''
    Method for initializing a kinetic model.
    Defines required inputs for all kinetic models.

    Args:
        t (temporalimage.Quantity): time corresponding to each point of the
                                    time activity curve (TAC)
        dt (temporalimage.Quantity): duration of each time frame
        TAC (numpy.ndarray): 1- or 2-D array.
                           each row is the time activity curve of a
                           region/voxel/vertex of interest.
                           if 1-D, can be a column or row vector
                           TAC and refTAC must be specified in the same units
        refTAC (numpy.array): time activity curve of the reference region
                              TAC and refTAC must be specified in the same units
        startActivity (str): one of 'flat', 'increasing', or 'zero'
            defines the method for determining the value of the initial
            integral \int_0^{t_0} TAC(t) dt (default: 'increasing')
            if 'flat', TAC(t)=TAC(t_0) for 0≤t<t_0, which results in this
                integral evaluating to t_0 * TAC(t_0)
            if 'increasing', TAC(t)=TAC(t_0) / t_0 * t for 0≤t<t_0,
                which results in this integral evaluating to t_0 * TAC(t_0) / 2
            if 'zero', TAC(t)=0 for 0≤t<t_0, which results in this integral
                evaluating to 0
        weights (str): one of 'none', 'frameduration', 'frameduration_activity',
            'frameduration_activity_decay', 'trues',
            or a custom 1- or 2-D np.array
            equivalent to the precision (inverse of variance) of each time
            frame; defines weights for each time frame in model fitting
            If weights is a vector, its length must be equal to length of t.
            If weights is a matrix, it must be of the same size as TAC.
            if 'none', each frame is weighted equally
            if 'frameduration', frame weight is proportional to dt
            if 'frameduration_activity', frame weight is proportional to dt / TAC
            if 'frameduration_activity_decay' (halflife must be specified),
                frame weight is proportional to dt / (TAC * exp(decayConstant * t)),
                where decayConstant = ln(2) / halflife
            if 'trues' (halflife and Trues must be specified), frame weight
                is proportional to dt^2 / (Trues * exp(decayConstant * t)^2)
            if custom vector, frame weight is proportional to corresponding
                vector element
            if custom matrix, each TAC can be assigned a different set of weights
        halflife (temporalimage.Quantity): required for decay corrected weights
    '''

    # implemented kinetic models
    model_values = ('SRTM_Zhou2003','SRTM_Lammertsma1996','SRTM_Gunn1997')

    # possible values for startActivity
    startActivity_values = ('flat','increasing','zero')

    # possible values for weights (or a custom vector)
    weights_values = ('frameduration','none',
                      'frameduration_activity',
                      'frameduration_activity_decay',
                      'trues')

    # NOTE: the first entry in the tuples above will be used as the default
    # option in code that has kineticmodel as a dependency
    # DO NOT MODIFY the first entry in the tuples above

    def __init__(self, t, dt, TAC, refTAC,
                 startActivity='flat',
                 weights='frameduration',
                 halflife=None,
                 Trues=None,
                 TAC_rownames=None):

        # basic input checks
        if not t.ndim==dt.ndim==refTAC.ndim==1:
            raise ValueError('KineticModel inputs t, dt, refTAC must be 1-D')
        if not len(t)==len(dt)==len(refTAC):
            raise ValueError('KineticModel inputs t, dt, refTAC must have same length')
        if not (t.check('[time]') and dt.check('[time]')):
            raise ValueError('t and dt should be specified in valid time units')

        if TAC.ndim==1:
            if not len(TAC)==len(t):
                raise ValueError('KineticModel inputs TAC and t must have same length')
            # make TAC into a row vector
            TAC = TAC[np.newaxis,:]
        elif TAC.ndim==2:
            if not TAC.shape[1]==len(t):
                raise ValueError('Number of columns of TAC must be the same \
                                  as length of t')
        else:
            raise ValueError('TAC must be 1- or 2-dimensional')

        if not np.all(np.isfinite(TAC)):
            raise ValueError('TAC must consist of finite values')

        if TAC_rownames is not None:
            if not length(TAC_rownames)==TAC.shape[0]:
                raise ValueError(('Number of TAC row names specified must be '
                                  'the same as the number of rows of TAC'))

        if not (t[0]>=0):
            raise ValueError('Time of initial frame must be >=0')
        if not strictly_increasing(t):
            raise ValueError('Time values must be monotonically increasing')
        if not all(dt>0):
            raise ValueError('Time frame durations must be >0')

        self.halflife = None
        if halflife is not None:
            if not halflife.check('[time]'):
                raise ValueError('Halflife should be specified in a valid time unit')
            elif halflife<=0:
                raise ValueError('Halflife should be positive')
            else:
                self.halflife = halflife.to('min').magnitude

        if not (startActivity in KineticModel.startActivity_values):
            raise ValueError('startActivity must be one of: ' + \
                             str(KineticModel.startActivity_values))

        # internally, store everything in minutes
        self.t = t.to('min').magnitude
        self.dt = dt.to('min').magnitude
        self.TAC = TAC
        self.refTAC = refTAC
        self.startActivity = startActivity
        self.TAC_rownames = TAC_rownames

        if weights=='none':
            self.weights = np.ones_like(self.TAC)
        elif weights=='frameduration':
            self.weights = np.tile(self.dt, (self.TAC.shape[0],1))
        elif weights=='frameduration_activity':
            self.weights = self.dt / self.TAC
        elif weights=='frameduration_activity_decay':
            # used in jip analysis toolkit:
            # http://www.nmr.mgh.harvard.edu/~jbm/jip/jip-srtm/noise-model.html
            # and in Turku PET Centre's software:
            # http://www.turkupetcentre.net/petanalysis/tpcclib/doc/fvar4dat.html
            if self.halflife is None:
                raise ValueError('Halflife must be specified for decay correction')
            decayConstant = np.log(2) / self.halflife
            self.weights = self.dt / (TAC * np.exp(decayConstant * self.t))
        elif weights=='trues':
            if self.halflife is None:
                raise ValueError('Halflife must be specified for trues correction')
            if Trues is None:
                raise ValueError('Trues must be specified')
            decayConstant = np.log(2) / self.halflife
            self.weights = np.square(self.dt) / \
                           (Trues * np.square(np.exp(decayConstant * self.t)))
        elif len(weights)==len(self.t):
            self.weights = np.tile(weights, (TAC.shape[0],1))
        elif weights.shape==TAC.shape:
            self.weights = weights
        else:
            raise ValueError('weights must be one of: ' + \
                             str(KineticModel.weights_values) + \
                             ' or must be a vector of same length as t')

        if np.any(self.weights<0):
            warnings.warn(('There are negative weights; '
                           'will replace them with their absolute value'))
            self.weights = np.absolute(self.weights)
        # normalize weights so that they sum to 1
        self.weights = self.weights / \
                       np.tile(np.sum(self.weights, axis=1).reshape(-1,1),
                               (1,self.weights.shape[1]))

        self.results = {}

        for result_name in self.__class__.result_names:
            self.results[result_name] = np.empty(self.TAC.shape[0])
            self.results[result_name].fill(np.nan)

    @abstractmethod
    def fit(self, **kwargs):
        # update self.results
        return self

    def save_results(self, filename):
        '''
        Write results of kinetic model fitting to csv file

        Args:
            filename (str): name of output csv file
        '''

        from pandas import DataFrame
        DataFrame(self.results, index=self.TAC_rownames).to_csv(filename)

    @classmethod
    def volume_wrapper(cls,
                       timeSeriesImgFile=None, frameTimingFile=None, ti=None,
                       refRegionMaskFile=None, refTAC=None,
                       startActivity='flat',
                       weights='frameduration', halflife=None, Trues=None,
                       **kwargs):
        '''
        Wrapper method for fitting a kinetic model on voxelwise imaging data.

        Either both of (timeSeriesImgFile, frameTimingFile) OR ti must be specified.
        Either refRegionMaskFile or refTAC must be specified.
        See KineticModel.__init__ for other optional arguments.
        SRTM_Zhou2003 requires the input fwhm, which determines the smoothing
        sigma.

        Args:
            timeSeriesImgFile (str): specification of 4D image file to load
            frameTimingFile (str): specification of the csv/sif/json file
                                   containing frame timing information
            ti (temporalimage.TemporalImage): the 4D image to operate on
            refRegionMaskFile (str): path to binary mask image
                                     (defines the reference region)
            refTAC (numpy.array): time activity curve of the reference region

        Returns:
            results_img (dict): dictionary with keys corresponding to results
                                computed by the kinetic model and values
                                corresponding to numpy.ndarray matrices
        '''

        import temporalimage
        from scipy.ndimage import gaussian_filter

        if not (timeSeriesImgFile is None)==(frameTimingFile is None):
            raise ValueError(('If either of timeSeriesImgFile and '
                              'frameTimingFile is specified, '
                              'both must be specified'))

        if not (timeSeriesImgFile is None) ^ (ti is None):
            raise TypeError(('Either (timeSeriesImgFile, frameTimingFile) '
                             'or ti must be specified'))

        if not (refRegionMaskFile is None) ^ (refTAC is None):
            raise TypeError('Either refRegionMaskFile or refTAC must be specified')

        if ti is None:
            ti = temporalimage.load(timeSeriesImgFile, frameTimingFile)
        img_dat = ti.get_fdata()

        if refTAC is None:
            # extract refTAC from image using roi_timeseries function
            refTAC = ti.roi_timeseries(maskfile=refRegionMaskFile)

        TAC = img_dat.reshape((ti.get_numVoxels(), ti.get_numFrames()))
        mip = np.amax(TAC,axis=1)
        # don't process voxels that don't have at least one count or that have non-finite values
        mask = np.all(np.isfinite(TAC), axis=1) & (mip>=1)
        TAC = TAC[mask,:]
        numVox = TAC.shape[0]

        # next, instantiate kineticmodel
        km = cls(ti.get_midTime(), ti.get_frameDuration(), TAC, refTAC,
                 startActivity=startActivity,
                 weights=weights, halflife=halflife, Trues=Trues)

        # a special case for Zhou 2003 implementation
        if cls.__name__=='SRTM_Zhou2003':
            if kwargs.get('fwhm', None) is None:
                raise ValueError('fwhm must be specified for SRTM_Zhou2003')

            voxSize = ti.header.get_zooms()[0:3]
            sigma_mm = kwargs['fwhm'] / (2*np.sqrt(2*np.log(2)))
            sigma = [sigma_mm / v for v in voxSize]

            # supply smoothed TAC for better performance
            smooth_img_dat = ti.gaussian_filter(sigma)
            smoothTAC = np.reshape(smooth_img_dat,
                                   (np.prod(smooth_img_dat.shape[:-1]),
                                    smooth_img_dat.shape[-1]))[mask,:]

            # fit model
            km.fit(smoothTAC=smoothTAC)

            # Refine R1
            R1_wlr_flat = np.zeros(ti.get_numVoxels())
            R1_wlr_flat[mask] = km.results['R1']
            R1_wlr = np.reshape(R1_wlr_flat, img_dat.shape[:-1])

            k2_wlr_flat = np.zeros(ti.get_numVoxels())
            k2_wlr_flat[mask] = km.results['k2']
            k2_wlr = np.reshape(k2_wlr_flat, img_dat.shape[:-1])

            k2a_wlr_flat = np.zeros(ti.get_numVoxels())
            k2a_wlr_flat[mask] = km.results['k2a']
            k2a_wlr = np.reshape(k2a_wlr_flat, img_dat.shape[:-1])

            smooth_R1_wlr = gaussian_filter(R1_wlr, sigma=sigma)
            smooth_k2_wlr = gaussian_filter(k2_wlr, sigma=sigma)
            smooth_k2a_wlr = gaussian_filter(k2a_wlr, sigma=sigma)

            smooth_R1_wlr_flat_masked = smooth_R1_wlr.flatten()[mask]
            smooth_k2_wlr_flat_masked = smooth_k2_wlr.flatten()[mask]
            smooth_k2a_wlr_flat_masked = smooth_k2a_wlr.flatten()[mask]

            m = 3
            h = np.zeros((numVox, m))

            h0_flat = np.zeros(ti.get_numVoxels())
            h0_flat[mask] = m * km.results['noiseVar_eqR1'] / \
                            np.square(km.results['R1'] - smooth_R1_wlr_flat_masked)
            h0 = np.reshape(h0_flat, img_dat.shape[:-1])

            h1_flat = np.zeros(ti.get_numVoxels())
            h1_flat[mask] = m * km.results['noiseVar_eqR1'] / \
                            np.square(km.results['k2'] - smooth_k2_wlr_flat_masked)
            h1 = np.reshape(h1_flat, img_dat.shape[:-1])

            h2_flat = np.zeros(ti.get_numVoxels())
            h2_flat[mask] = m * km.results['noiseVar_eqR1'] / \
                            np.square(km.results['k2a'] - smooth_k2a_wlr_flat_masked)
            h2 = np.reshape(h2_flat, img_dat.shape[:-1])

            h[:,0] = gaussian_filter(h0, sigma=sigma).flatten()[mask]
            h[:,1] = gaussian_filter(h1, sigma=sigma).flatten()[mask]
            h[:,2] = gaussian_filter(h2, sigma=sigma).flatten()[mask]

            km.refine_R1(smooth_R1_wlr_flat_masked,
                         smooth_k2_wlr_flat_masked,
                         smooth_k2a_wlr_flat_masked, h)
        else:
            km.fit()

        results_img = {}
        for result_name in cls.result_names:
            res = np.empty(ti.get_numVoxels())
            res.fill(np.nan)
            res[mask] = km.results[result_name]
            results_img[result_name] = np.reshape(res, img_dat.shape[:-1])

        return results_img

    @classmethod
    def surface_wrapper(cls,
                        refTAC=None,
                        startActivity='flat',
                        weights='frameduration',
                        **kwargs):
        '''
        Wrapper method for fitting a kinetic model on vertexwise imaging data.

        Either both of (timeSeriesSurfaceFile, frameTimingFile) OR tiSurf must be specified.
        Either refRegionMaskFile and a timeSeriesImgFile or refTAC must be specified.
        See KineticModel.__init__ for other optional arguments.
        SRTM_Zhou2003 requires the input fwhm, which determines the smoothing
        sigma.

        Args:
            timeSeriesSurfaceFile (str): path to 4D surface image
                                         (2 dimensions are set to 1)
            frameTimingFile (str): path to csv/sif/json file containing frame
                                   timing information
            tiSurf (temporalimage.TemporalImage): surface as TemporalImage
            refRegionMaskFile (str): path to binary mask image defining the reference region
            timeSeriesImgFile (str): path to 4D image file to load
            refTAC (numpy.array) time activity curve of the reference region

        Returns:
            results_img (dict): dictionary with keys corresponding to results
                                computed by the kinetic model and values
                                corresponding to numpy.ndarray matrices
        '''

        import temporalimage

        if not (timeSeriesSurfaceFile is None)==(frameTimingFile is None):
            raise ValueError(('If either of timeSeriesSurfaceFile and '
                              'frameTimingFile is specified, '
                              'both must be specified'))

        if not (timeSeriesSurfaceFile is None) ^ (tiSurf is None):
            raise TypeError(('Either (timeSeriesSurfaceFile, frameTimingFile) '
                             'or ti must be specified'))

        if not (refRegionMaskFile is None) ^ (refTAC is None):
            raise TypeError('Either refRegionMaskFile or refTAC must be specified')

        if tiSurf is None:
            tiSurf = temporalimage.load(timeSeriesSurfaceFile, frameTimingFile)
        img_dat = tiSurf.get_fdata()

        if refTAC is None:
            # extract refTAC from image using roi_timeseries function
            ti = temporalimage.load(timeSeriesImgFile, frameTimingFile)
            refTAC = ti.roi_timeseries(maskfile=refRegionMaskFile)

        TAC = img_dat.reshape((ti.get_numVoxels(), ti.get_numFrames()))
        mip = np.amax(TAC,axis=1)
        # don't process voxels that don't have at least one count or that have non-finite values
        mask = np.all(np.isfinite(TAC), axis=1) & (mip>=1)
        TAC = TAC[mask,:]
        numVox = TAC.shape[0]

        # next, instantiate kineticmodel
        km = cls(ti.get_midTime(), ti.get_frameDuration(), TAC, refTAC,
                 startActivity=startActivity,
                 weights=weights, halflife=halflife, Trues=Trues)

        # a special case for Zhou 2003 implementation
        if cls.__name__=='SRTM_Zhou2003':
            NotImplementedError("Surface smoothing still needs to be implemented")
        else:
            km.fit()

        results_img = {}
        for result_name in cls.result_names:
            res = np.empty(ti.get_numVoxels())
            res.fill(np.nan)
            res[mask] = km.results[result_name]
            results_img[result_name] = np.reshape(res, img_dat.shape[:-1])

        return results_img

def strictly_increasing(L):
    '''
    Check if L is a monotonically increasing vector

    Args:
        L (numpy.array): 1-D array

    Returns:
        is_strictly_increasing (bool): True if L is strictly increasing
    '''
    is_strictly_increasing = all(x<y for x, y in zip(L, L[1:]))
    return is_strictly_increasing

def integrate(TAC, t, startActivity='flat'):
    '''
    Static method to perform time activity curve integration.

    Args:
        TAC (numpy.array): 1-D array. time activity curve
        t (numpy.array): 1-D array. time
        startActivity (str): 'flat', 'increasing', or 'zero'

    Returns:
        intTAC (numpy.array): 1-D array. integrated time activity curve
    '''
    if not TAC.ndim==t.ndim==1:
        raise ValueError('TAC must be 1-dimensional')
    if not len(t)==len(TAC):
        raise ValueError('TAC and t must have same length')
    if not (startActivity in KineticModel.startActivity_values):
        raise ValueError('startActivity must be one of: ' + \
                         str(KineticModel.startActivity_values))

    if startActivity=='flat':
        # assume TAC(t)=TAC(t_0) for 0≤t<t_0
        initialIntegralValue = t[0]*TAC[0]
    elif startActivity=='increasing':
        # assume TAC(t)=TAC(t_0) / t_0 * t for 0≤t<t_0
        initialIntegralValue = t[0]*TAC[0]/2
    elif startActivity=='zero':
        # assume TAC(t)=0 for 0≤t<t_0
        initialIntegralValue = 0

    # Numerical integration of TAC
    intTAC = sp_integrate.cumtrapz(TAC,t,initial=initialIntegralValue)

    return intTAC
