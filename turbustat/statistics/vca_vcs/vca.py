# Licensed under an MIT open source license - see LICENSE


import numpy as np
import statsmodels.api as sm
import warnings
from numpy.fft import fftshift

from ..lm_seg import Lm_Seg
from ..psds import pspec
from ..rfft_to_fft import rfft_to_fft
from slice_thickness import change_slice_thickness


class VCA(object):

    '''
    The VCA technique (Lazarian & Pogosyan, 2004).

    Parameters
    ----------
    cube : numpy.ndarray
        Data cube.
    header : FITS header
        Corresponding FITS header.
    slice_sizes : float or int, optional
        Slices to degrade the cube to.
    ang_units : bool, optional
        Convert frequencies to angular units using the given header.
    '''

    def __init__(self, cube, header, slice_size=None, ang_units=False):
        super(VCA, self).__init__()

        self.cube = cube.astype("float64")
        if np.isnan(self.cube).any():
            self.cube[np.isnan(self.cube)] = 0
            # Feel like this should be more specific
            self.good_channel_count = np.sum(self.cube.max(axis=0) != 0)
        self.header = header
        self.shape = self.cube.shape

        if slice_size is None:
            self.slice_size = 1.0

        if slice_size != 1.0:
            self.cube = \
                change_slice_thickness(self.cube,
                                       slice_thickness=self.slice_size)

        self.ang_units = ang_units

        self._ps1D_stddev = None

    @property
    def ps2D(self):
        return self._ps2D

    @property
    def ps1D(self):
        return self._ps1D

    @property
    def ps1D_stddev(self):
        if not self._stddev_flag:
            Warning("ps1D_stddev is only calculated when return_stddev"
                    " is enabled.")

        return self._ps1D_stddev

    @property
    def freqs(self):
        return self._freqs

    def compute_pspec(self):
        '''
        Compute the 2D power spectrum.
        '''

        vca_fft = fftshift(rfft_to_fft(self.cube))

        self._ps2D = np.power(vca_fft, 2.).sum(axis=0)

    def compute_radial_pspec(self, return_stddev=True,
                             logspacing=True, **kwargs):
        '''
        Computes the radially averaged power spectrum.

        Parameters
        ----------
        return_stddev : bool, optional
            Return the standard deviation in the 1D bins.
        logspacing : bool, optional
            Return logarithmically spaced bins for the lags.
        kwargs : passed to pspec
        '''

        if return_stddev:
            self._freqs, self._ps1D, self._ps1D_stddev = \
                pspec(self.ps2D, return_stddev=return_stddev,
                      logspacing=logspacing, **kwargs)
            self._stddev_flag = True
        else:
            self._freqs, self._ps1D = \
                pspec(self.ps2D, return_stddev=return_stddev,
                      **kwargs)
            self._stddev_flag = False

        if self.ang_units:
            self._freqs *= np.abs(self.header["CDELT2"]) ** -1.

    def fit_pspec(self, brk=None, log_break=False, low_cut=None,
                  min_fits_pts=10, verbose=False):
        '''
        Fit the 1D Power spectrum using a segmented linear model. Note that
        the current implementation allows for only 1 break point in the
        model. If the break point is estimated via a spline, the breaks are
        tested, starting from the largest, until the model finds a good fit.

        Parameters
        ----------
        brk : float or None, optional
            Guesses for the break points. If given as a list, the length of
            the list sets the number of break points to be fit. If a choice is
            outside of the allowed range from the data, Lm_Seg will raise an
            error. If None, a spline is used to estimate the breaks.
        log_break : bool, optional
            Sets whether the provided break estimates are log-ed values.
        lg_scale_cut : int, optional
            Cuts off largest scales, which deviate from the powerlaw.
        min_fits_pts : int, optional
            Sets the minimum number of points needed to fit. If not met, the
            break found is rejected.
        verbose : bool, optional
            Enables verbose mode in Lm_Seg.
        '''

        # Make the data to fit to
        if low_cut is None:
            # Default to the largest frequency, since this is just 1 pixel
            # in the 2D PSpec.
            self.low_cut = 1/float(max(self.ps2D.shape))
        else:
            self.low_cut = low_cut
        x = np.log10(self.freqs[self.freqs > self.low_cut])
        y = np.log10(self.ps1D[self.freqs > self.low_cut])

        if brk is not None:
            # Try the fit with a break in it.
            if not log_break:
                brk = np.log10(brk)

            brk_fit = \
                Lm_Seg(x, y, brk)
            brk_fit.fit_model(verbose=verbose)

            if brk_fit.params.size == 5:

                # Check to make sure this leaves enough to fit to.
                if sum(x < brk_fit.brk) < min_fits_pts:
                    warnings.warn("Not enough points to fit to." +
                                  " Ignoring break.")

                    self.high_cut = self.freqs.max()
                else:
                    x = x[x < brk_fit.brk]
                    y = y[x < brk_fit.brk]

                    self.high_cut = 10**brk_fit.brk

            else:
                self.high_cut = self.freqs.max()
                # Break fit failed, revert to normal model
                warnings.warn("Model with break failed, reverting to model\
                               without break.")
        else:
            self.high_cut = self.freqs.max()

        x = sm.add_constant(x)

        model = sm.OLS(y, x, missing='drop')

        self.fit = model.fit()

        self._slope = self.fit.params[1]

        self._slope_err = self.fit.bse[1]

    @property
    def slope(self):
        return self._slope

    @property
    def slope_err(self):
        return self._slope_err

    def plot_fit(self, show=True, show_2D=False, color='r', label=None,
                 symbol="D"):
        '''
        Plot the fitted model.
        '''

        import matplotlib.pyplot as p

        if self.ang_units:
            xlab = r"log k/deg$^{-1}$"
        else:
            xlab = r"log k/pixel$^{-1}$"

        # 2D Spectrum is shown alongside 1D. Otherwise only 1D is returned.
        if show_2D:
            p.subplot(122)
            p.imshow(np.log10(self.ps2D), interpolation="nearest",
                     origin="lower")
            p.colorbar()

            ax = p.subplot(121)
        else:
            ax = p.subplot(111)

        good_interval = np.logical_and(self.freqs >= self.low_cut,
                                       self.freqs <= self.high_cut)

        y_fit = self.fit.fittedvalues
        fit_index = np.logical_and(np.isfinite(self.ps1D), good_interval)

        ax.loglog(self.freqs[fit_index], 10**y_fit, color+'-',
                  linewidth=2)
        ax.set_xlabel(xlab)
        ax.set_ylabel(r"P$_2(k)$")

        if self._stddev_flag:
            ax.errorbar(self.freqs[good_interval], self.ps1D[good_interval],
                        yerr=self.ps1D_stddev[good_interval], color=color,
                        fmt=symbol, alpha=0.5, capsize=10,
                        elinewidth=3, label=label)
            ax.set_xscale("log", nonposy='clip')
            ax.set_yscale("log", nonposy='clip')
        else:
            p.loglog(self.freqs[good_interval],
                     self.ps1D[good_interval], color+symbol, alpha=0.5,
                     label=label)

        p.grid(True)

        if show:
            p.show()

    def run(self, verbose=False, brk=None, return_stddev=True,
            logspacing=True):
        '''
        Full computation of VCA.

        Parameters
        ----------
        verbose : bool, optional
            Enables plotting.
        brk : float, optional
            Initial guess for the break point.
        return_stddev : bool, optional
            Return the standard deviation in the 1D bins.
        logspacing : bool, optional
            Return logarithmically spaced bins for the lags.
        '''

        self.compute_pspec()
        self.compute_radial_pspec(return_stddev=return_stddev)
        self.fit_pspec(brk=brk)

        if verbose:

            print self.fit.summary()

            self.plot_fit(show=True, show_2D=True)

        return self


class VCA_Distance(object):

    '''
    Calculate the distance between two cubes using VCA. The 1D power spectrum
    is modeled by a linear model. The distance is the t-statistic of the
    interaction between the two slopes.

    Parameters
    ----------
    cube1 : FITS hdu
        Data cube.
    cube2 : FITS hdu
        Data cube.
    slice_size : float, optional
        Slice to degrade the cube to.
    breaks : float, list or array, optional
        Specify where the break point is. If None, attempts to find using
        spline. If not specified, no break point will be used.
    fiducial_model : VCA
        Computed VCA object. use to avoid recomputing.
    ang_units : bool, optional
        Convert frequencies to angular units using the given header.
    '''

    def __init__(self, cube1, cube2, slice_size=1.0, breaks=None,
                 fiducial_model=None, ang_units=False):
        super(VCA_Distance, self).__init__()
        cube1, header1 = cube1
        cube2, header2 = cube2

        self.ang_units = ang_units

        assert isinstance(slice_size, float)

        if not isinstance(breaks, list) or not isinstance(breaks, np.ndarray):
            breaks = [breaks] * 2

        if fiducial_model is not None:
            self.vca1 = fiducial_model
        else:
            self.vca1 = \
                VCA(cube1, header1, slice_size=slice_size,
                    ang_units=ang_units).run(brk=breaks[0])

        self.vca2 = \
            VCA(cube2, header2, slice_size=slice_size,
                ang_units=ang_units).run(brk=breaks[1])

    def distance_metric(self, verbose=False, label1=None, label2=None):
        '''

        Implements the distance metric for 2 VCA transforms, each with the
        same channel width. We fit the linear portion of the transform to
        represent the powerlaw.

        Parameters
        ----------
        verbose : bool, optional
            Enables plotting.
        label1 : str, optional
            Object or region name for cube1
        label2 : str, optional
            Object or region name for cube2
        '''

        # Construct t-statistic
        self.distance = \
            np.abs((self.vca1.slope - self.vca2.slope) /
                   np.sqrt(self.vca1.slope_err**2 +
                           self.vca2.slope_err**2))

        if verbose:

            print "Fit to %s" % (label1)
            print self.vca1.fit.summary()
            print "Fit to %s" % (label2)
            print self.vca2.fit.summary()

            import matplotlib.pyplot as p
            self.vca1.plot_fit(show=False, color='b', label=label1, symbol='D')
            self.vca2.plot_fit(show=False, color='r', label=label2, symbol='o')
            p.legend(loc='upper right')
            p.show()

        return self
