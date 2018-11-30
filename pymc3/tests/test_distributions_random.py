from __future__ import division

import pytest
import numpy as np
import numpy.testing as npt
import scipy.stats as st
from scipy.special import expit
from scipy import linalg
import numpy.random as nr
import theano

import pymc3 as pm
from pymc3.distributions.distribution import draw_values
from .helpers import SeededTest
from .test_distributions import (
    build_model, Domain, product, R, Rplus, Rplusbig, Rplusdunif,
    Unit, Nat, NatSmall, I, Simplex, Vector, PdMatrix,
    PdMatrixChol, PdMatrixCholUpper, RealMatrix, RandomPdMatrix
)


def pymc3_random(dist, paramdomains, ref_rand, valuedomain=Domain([0]),
                 size=10000, alpha=0.05, fails=10, extra_args=None,
                 model_args=None):
    if model_args is None:
        model_args = {}
    model = build_model(dist, valuedomain, paramdomains, extra_args)
    domains = paramdomains.copy()
    for pt in product(domains, n_samples=100):
        pt = pm.Point(pt, model=model)
        pt.update(model_args)
        p = alpha
        # Allow KS test to fail (i.e., the samples be different)
        # a certain number of times. Crude, but necessary.
        f = fails
        while p <= alpha and f > 0:
            s0 = model.named_vars['value'].random(size=size, point=pt)
            s1 = ref_rand(size=size, **pt)
            _, p = st.ks_2samp(np.atleast_1d(s0).flatten(),
                               np.atleast_1d(s1).flatten())
            f -= 1
        assert p > alpha, str(pt)


def pymc3_random_discrete(dist, paramdomains,
                          valuedomain=Domain([0]), ref_rand=None,
                          size=100000, alpha=0.05, fails=20):
    model = build_model(dist, valuedomain, paramdomains)
    domains = paramdomains.copy()
    for pt in product(domains, n_samples=100):
        pt = pm.Point(pt, model=model)
        p = alpha
        # Allow Chisq test to fail (i.e., the samples be different)
        # a certain number of times.
        f = fails
        while p <= alpha and f > 0:
            o = model.named_vars['value'].random(size=size, point=pt)
            e = ref_rand(size=size, **pt)
            o = np.atleast_1d(o).flatten()
            e = np.atleast_1d(e).flatten()
            observed = dict(zip(*np.unique(o, return_counts=True)))
            expected = dict(zip(*np.unique(e, return_counts=True)))
            for e in expected.keys():
                expected[e] = (observed.get(e, 0), expected[e])
            k = np.array([v for v in expected.values()])
            if np.all(k[:, 0] == k[:, 1]):
                p = 1.
            else:
                _, p = st.chisquare(k[:, 0], k[:, 1])
            f -= 1
        assert p > alpha, str(pt)


class TestDrawValues(SeededTest):
    def test_draw_scalar_parameters(self):
        with pm.Model():
            y = pm.Normal('y1', mu=0., sd=1.)
            mu, tau = draw_values([y.distribution.mu, y.distribution.tau])
        npt.assert_almost_equal(mu, 0)
        npt.assert_almost_equal(tau, 1)

    def test_draw_dependencies(self):
        with pm.Model():
            x = pm.Normal('x', mu=0., sd=1.)
            exp_x = pm.Deterministic('exp_x', pm.math.exp(x))

        x, exp_x = draw_values([x, exp_x])
        npt.assert_almost_equal(np.exp(x), exp_x)

    def test_draw_order(self):
        with pm.Model():
            x = pm.Normal('x', mu=0., sd=1.)
            exp_x = pm.Deterministic('exp_x', pm.math.exp(x))

        # Need to draw x before drawing log_x
        exp_x, x = draw_values([exp_x, x])
        npt.assert_almost_equal(np.exp(x), exp_x)

    def test_draw_point_replacement(self):
        with pm.Model():
            mu = pm.Normal('mu', mu=0., tau=1e-3)
            sigma = pm.Gamma('sigma', alpha=1., beta=1., transform=None)
            y = pm.Normal('y', mu=mu, sd=sigma)
            mu2, tau2 = draw_values([y.distribution.mu, y.distribution.tau],
                                                     point={'mu': 5., 'sigma': 2.})
        npt.assert_almost_equal(mu2, 5)
        npt.assert_almost_equal(tau2, 1 / 2.**2)

    def test_random_sample_returns_nd_array(self):
        with pm.Model():
            mu = pm.Normal('mu', mu=0., tau=1e-3)
            sigma = pm.Gamma('sigma', alpha=1., beta=1., transform=None)
            y = pm.Normal('y', mu=mu, sd=sigma)
            mu, tau = draw_values([y.distribution.mu, y.distribution.tau])
        assert isinstance(mu, np.ndarray)
        assert isinstance(tau, np.ndarray)


class BaseTestCases(object):
    class BaseTestCase(SeededTest):
        shape = 5

        def setup_method(self, *args, **kwargs):
            super(BaseTestCases.BaseTestCase, self).setup_method(*args, **kwargs)
            self.model = pm.Model()

        def get_random_variable(self, shape, with_vector_params=False, name=None):
            if with_vector_params:
                params = {key: value * np.ones(self.shape, dtype=np.dtype(type(value))) for
                          key, value in self.params.items()}
            else:
                params = self.params
            if name is None:
                name = self.distribution.__name__
            with self.model:
                if shape is None:
                    return self.distribution(name, transform=None, **params)
                else:
                    return self.distribution(name, shape=shape, transform=None, **params)

        @staticmethod
        def sample_random_variable(random_variable, size):
            try:
                return random_variable.random(size=size)
            except AttributeError:
                return random_variable.distribution.random(size=size)

        @pytest.mark.parametrize('size', [None, 5, (4, 5)], ids=str)
        def test_scalar_parameter_shape(self, size):
            rv = self.get_random_variable(None)
            if size is None:
                expected = 1,
            else:
                expected = np.atleast_1d(size).tolist()
            actual = np.atleast_1d(self.sample_random_variable(rv, size)).shape
            assert tuple(expected) == actual

        @pytest.mark.parametrize('size', [None, 5, (4, 5)], ids=str)
        def test_scalar_shape(self, size):
            shape = 10
            rv = self.get_random_variable(shape)

            if size is None:
                expected = []
            else:
                expected = np.atleast_1d(size).tolist()
            expected.append(shape)
            actual = np.atleast_1d(self.sample_random_variable(rv, size)).shape
            assert tuple(expected) == actual

        @pytest.mark.parametrize('size', [None, 5, (4, 5)], ids=str)
        def test_parameters_1d_shape(self, size):
            rv = self.get_random_variable(self.shape, with_vector_params=True)
            if size is None:
                expected = []
            else:
                expected = np.atleast_1d(size).tolist()
            expected.append(self.shape)
            actual = self.sample_random_variable(rv, size).shape
            assert tuple(expected) == actual

        @pytest.mark.parametrize('size', [None, 5, (4, 5)], ids=str)
        def test_broadcast_shape(self, size):
            broadcast_shape = (2 * self.shape, self.shape)
            rv = self.get_random_variable(broadcast_shape, with_vector_params=True)
            if size is None:
                expected = []
            else:
                expected = np.atleast_1d(size).tolist()
            expected.extend(broadcast_shape)
            actual = np.atleast_1d(self.sample_random_variable(rv, size)).shape
            assert tuple(expected) == actual

        @pytest.mark.parametrize('shape', [(), (1,), (1, 1), (1, 2), (10, 10, 1), (10, 10, 2)], ids=str)
        def test_different_shapes_and_sample_sizes(self, shape):
            prefix = self.distribution.__name__

            rv = self.get_random_variable(shape, name='%s_%s' % (prefix, shape))
            for size in (None, 1, 5, (4, 5)):
                if size is None:
                    s = []
                else:
                    try:
                        s = list(size)
                    except TypeError:
                        s = [size]
                    if s == [1]:
                        s = []
                if shape not in ((), (1,)):
                    s.extend(shape)
                e = tuple(s)
                a = self.sample_random_variable(rv, size).shape
                assert e == a


class TestNormal(BaseTestCases.BaseTestCase):
    distribution = pm.Normal
    params = {'mu': 0., 'tau': 1.}

class TestTruncatedNormal(BaseTestCases.BaseTestCase):
    distribution = pm.TruncatedNormal
    params = {'mu': 0., 'tau': 1., 'lower':-0.5, 'upper':0.5}

class TestTruncatedNormalLower(BaseTestCases.BaseTestCase):
    distribution = pm.TruncatedNormal
    params = {'mu': 0., 'tau': 1., 'lower':-0.5}

class TestTruncatedNormalUpper(BaseTestCases.BaseTestCase):
    distribution = pm.TruncatedNormal
    params = {'mu': 0., 'tau': 1., 'upper':0.5}

class TestSkewNormal(BaseTestCases.BaseTestCase):
    distribution = pm.SkewNormal
    params = {'mu': 0., 'sd': 1., 'alpha': 5.}


class TestHalfNormal(BaseTestCases.BaseTestCase):
    distribution = pm.HalfNormal
    params = {'tau': 1.}


class TestUniform(BaseTestCases.BaseTestCase):
    distribution = pm.Uniform
    params = {'lower': 0., 'upper': 1.}


class TestTriangular(BaseTestCases.BaseTestCase):
    distribution = pm.Triangular
    params = {'c': 0.5, 'lower': 0., 'upper': 1.}


class TestWald(BaseTestCases.BaseTestCase):
    distribution = pm.Wald
    params = {'mu': 1., 'lam': 1., 'alpha': 0.}


class TestBeta(BaseTestCases.BaseTestCase):
    distribution = pm.Beta
    params = {'alpha': 1., 'beta': 1.}


class TestKumaraswamy(BaseTestCases.BaseTestCase):
    distribution = pm.Kumaraswamy
    params = {'a': 1., 'b': 1.}


class TestExponential(BaseTestCases.BaseTestCase):
    distribution = pm.Exponential
    params = {'lam': 1.}


class TestLaplace(BaseTestCases.BaseTestCase):
    distribution = pm.Laplace
    params = {'mu': 1., 'b': 1.}


class TestLognormal(BaseTestCases.BaseTestCase):
    distribution = pm.Lognormal
    params = {'mu': 1., 'tau': 1.}


class TestStudentT(BaseTestCases.BaseTestCase):
    distribution = pm.StudentT
    params = {'nu': 5., 'mu': 0., 'lam': 1.}


class TestPareto(BaseTestCases.BaseTestCase):
    distribution = pm.Pareto
    params = {'alpha': 0.5, 'm': 1.}


class TestCauchy(BaseTestCases.BaseTestCase):
    distribution = pm.Cauchy
    params = {'alpha': 1., 'beta': 1.}


class TestHalfCauchy(BaseTestCases.BaseTestCase):
    distribution = pm.HalfCauchy
    params = {'beta': 1.}


class TestGamma(BaseTestCases.BaseTestCase):
    distribution = pm.Gamma
    params = {'alpha': 1., 'beta': 1.}


class TestInverseGamma(BaseTestCases.BaseTestCase):
    distribution = pm.InverseGamma
    params = {'alpha': 0.5, 'beta': 0.5}


class TestChiSquared(BaseTestCases.BaseTestCase):
    distribution = pm.ChiSquared
    params = {'nu': 2.}


class TestWeibull(BaseTestCases.BaseTestCase):
    distribution = pm.Weibull
    params = {'alpha': 1., 'beta': 1.}


class TestExGaussian(BaseTestCases.BaseTestCase):
    distribution = pm.ExGaussian
    params = {'mu': 0., 'sigma': 1., 'nu': 1.}


class TestVonMises(BaseTestCases.BaseTestCase):
    distribution = pm.VonMises
    params = {'mu': 0., 'kappa': 1.}


class TestGumbel(BaseTestCases.BaseTestCase):
    distribution = pm.Gumbel
    params = {'mu': 0., 'beta': 1.}


class TestLogistic(BaseTestCases.BaseTestCase):
    distribution = pm.Logistic
    params = {'mu': 0., 's': 1.}


class TestLogitNormal(BaseTestCases.BaseTestCase):
    distribution = pm.LogitNormal
    params = {'mu': 0., 'sd': 1.}


class TestBinomial(BaseTestCases.BaseTestCase):
    distribution = pm.Binomial
    params = {'n': 5, 'p': 0.5}


class TestBetaBinomial(BaseTestCases.BaseTestCase):
    distribution = pm.BetaBinomial
    params = {'n': 5, 'alpha': 1., 'beta': 1.}


class TestBernoulli(BaseTestCases.BaseTestCase):
    distribution = pm.Bernoulli
    params = {'p': 0.5}


class TestDiscreteWeibull(BaseTestCases.BaseTestCase):
    distribution = pm.DiscreteWeibull
    params = {'q': 0.25, 'beta': 2.}


class TestPoisson(BaseTestCases.BaseTestCase):
    distribution = pm.Poisson
    params = {'mu': 1.}


class TestNegativeBinomial(BaseTestCases.BaseTestCase):
    distribution = pm.NegativeBinomial
    params = {'mu': 1., 'alpha': 1.}


class TestConstant(BaseTestCases.BaseTestCase):
    distribution = pm.Constant
    params = {'c': 3}


class TestZeroInflatedPoisson(BaseTestCases.BaseTestCase):
    distribution = pm.ZeroInflatedPoisson
    params = {'theta': 1., 'psi': 0.3}


class TestZeroInflatedNegativeBinomial(BaseTestCases.BaseTestCase):
    distribution = pm.ZeroInflatedNegativeBinomial
    params = {'mu': 1., 'alpha': 1., 'psi': 0.3}

class TestZeroInflatedBinomial(BaseTestCases.BaseTestCase):
    distribution = pm.ZeroInflatedBinomial
    params = {'n': 10, 'p': 0.6, 'psi': 0.3}

class TestDiscreteUniform(BaseTestCases.BaseTestCase):
    distribution = pm.DiscreteUniform
    params = {'lower': 0., 'upper': 10.}


class TestGeometric(BaseTestCases.BaseTestCase):
    distribution = pm.Geometric
    params = {'p': 0.5}


class TestCategorical(BaseTestCases.BaseTestCase):
    distribution = pm.Categorical
    params = {'p': np.ones(BaseTestCases.BaseTestCase.shape)}

    def get_random_variable(self, shape, with_vector_params=False, **kwargs):  # don't transform categories
        return super(TestCategorical, self).get_random_variable(shape, with_vector_params=False, **kwargs)

    def test_probability_vector_shape(self):
        """Check that if a 2d array of probabilities are passed to categorical correct shape is returned"""
        p = np.ones((10, 5))
        assert pm.Categorical.dist(p=p).random().shape == (10,)


class TestScalarParameterSamples(SeededTest):
    def test_bounded(self):
        # A bit crude...
        BoundedNormal = pm.Bound(pm.Normal, upper=0)

        def ref_rand(size, tau):
            return -st.halfnorm.rvs(size=size, loc=0, scale=tau ** -0.5)
        pymc3_random(BoundedNormal, {'tau': Rplus}, ref_rand=ref_rand)

    def test_uniform(self):
        def ref_rand(size, lower, upper):
            return st.uniform.rvs(size=size, loc=lower, scale=upper - lower)
        pymc3_random(pm.Uniform, {'lower': -Rplus, 'upper': Rplus}, ref_rand=ref_rand)

    def test_normal(self):
        def ref_rand(size, mu, sd):
            return st.norm.rvs(size=size, loc=mu, scale=sd)
        pymc3_random(pm.Normal, {'mu': R, 'sd': Rplus}, ref_rand=ref_rand)

    def test_truncated_normal(self):
        def ref_rand(size, mu, sd, lower, upper):
            return st.truncnorm.rvs((lower-mu)/sd, (upper-mu)/sd, size=size, loc=mu, scale=sd)
        pymc3_random(pm.TruncatedNormal, {'mu': R, 'sd': Rplusbig, 'lower':-Rplusbig, 'upper':Rplusbig},
                     ref_rand=ref_rand)

    def test_truncated_normal_lower(self):
        def ref_rand(size, mu, sd, lower, upper):
            return st.truncnorm.rvs((lower-mu)/sd, np.inf, size=size, loc=mu, scale=sd)
        pymc3_random(pm.TruncatedNormal, {'mu': R, 'sd': Rplusbig, 'lower':-Rplusbig, 'upper':Rplusbig},
                     ref_rand=ref_rand)

    def test_truncated_normal_upper(self):
        def ref_rand(size, mu, sd, lower, upper):
            return st.truncnorm.rvs(-np.inf, (upper-mu)/sd, size=size, loc=mu, scale=sd)
        pymc3_random(pm.TruncatedNormal, {'mu': R, 'sd': Rplusbig, 'lower':-Rplusbig, 'upper':Rplusbig},
                     ref_rand=ref_rand)

    def test_skew_normal(self):
        def ref_rand(size, alpha, mu, sd):
            return st.skewnorm.rvs(size=size, a=alpha, loc=mu, scale=sd)
        pymc3_random(pm.SkewNormal, {'mu': R, 'sd': Rplus, 'alpha': R}, ref_rand=ref_rand)

    def test_half_normal(self):
        def ref_rand(size, tau):
            return st.halfnorm.rvs(size=size, loc=0, scale=tau ** -0.5)
        pymc3_random(pm.HalfNormal, {'tau': Rplus}, ref_rand=ref_rand)

    def test_wald(self):
        # Cannot do anything too exciting as scipy wald is a
        # location-scale model of the *standard* wald with mu=1 and lam=1
        def ref_rand(size, mu, lam, alpha):
            return st.wald.rvs(size=size, loc=alpha)
        pymc3_random(pm.Wald,
                     {'mu': Domain([1., 1., 1.]), 'lam': Domain(
                         [1., 1., 1.]), 'alpha': Rplus},
                     ref_rand=ref_rand)

    def test_beta(self):
        def ref_rand(size, alpha, beta):
            return st.beta.rvs(a=alpha, b=beta, size=size)
        pymc3_random(pm.Beta, {'alpha': Rplus, 'beta': Rplus}, ref_rand=ref_rand)

    def test_exponential(self):
        def ref_rand(size, lam):
            return nr.exponential(scale=1. / lam, size=size)
        pymc3_random(pm.Exponential, {'lam': Rplus}, ref_rand=ref_rand)

    def test_laplace(self):
        def ref_rand(size, mu, b):
            return st.laplace.rvs(mu, b, size=size)
        pymc3_random(pm.Laplace, {'mu': R, 'b': Rplus}, ref_rand=ref_rand)

    def test_lognormal(self):
        def ref_rand(size, mu, tau):
            return np.exp(mu + (tau ** -0.5) * st.norm.rvs(loc=0., scale=1., size=size))
        pymc3_random(pm.Lognormal, {'mu': R, 'tau': Rplusbig}, ref_rand=ref_rand)

    def test_student_t(self):
        def ref_rand(size, nu, mu, lam):
            return st.t.rvs(nu, mu, lam**-.5, size=size)
        pymc3_random(pm.StudentT, {'nu': Rplus, 'mu': R, 'lam': Rplus}, ref_rand=ref_rand)

    def test_cauchy(self):
        def ref_rand(size, alpha, beta):
            return st.cauchy.rvs(alpha, beta, size=size)
        pymc3_random(pm.Cauchy, {'alpha': R, 'beta': Rplusbig}, ref_rand=ref_rand)

    def test_half_cauchy(self):
        def ref_rand(size, beta):
            return st.halfcauchy.rvs(scale=beta, size=size)
        pymc3_random(pm.HalfCauchy, {'beta': Rplusbig}, ref_rand=ref_rand)

    def test_gamma_alpha_beta(self):
        def ref_rand(size, alpha, beta):
            return st.gamma.rvs(alpha, scale=1. / beta, size=size)
        pymc3_random(pm.Gamma, {'alpha': Rplusbig, 'beta': Rplusbig}, ref_rand=ref_rand)

    def test_gamma_mu_sd(self):
        def ref_rand(size, mu, sd):
            return st.gamma.rvs(mu**2 / sd**2, scale=sd ** 2 / mu, size=size)
        pymc3_random(pm.Gamma, {'mu': Rplusbig, 'sd': Rplusbig}, ref_rand=ref_rand)

    def test_inverse_gamma(self):
        def ref_rand(size, alpha, beta):
            return st.invgamma.rvs(a=alpha, scale=beta, size=size)
        pymc3_random(pm.InverseGamma, {'alpha': Rplus, 'beta': Rplus}, ref_rand=ref_rand)

    def test_pareto(self):
        def ref_rand(size, alpha, m):
            return st.pareto.rvs(alpha, scale=m, size=size)
        pymc3_random(pm.Pareto, {'alpha': Rplusbig, 'm': Rplusbig}, ref_rand=ref_rand)

    def test_ex_gaussian(self):
        def ref_rand(size, mu, sigma, nu):
            return nr.normal(mu, sigma, size=size) + nr.exponential(scale=nu, size=size)
        pymc3_random(pm.ExGaussian, {'mu': R, 'sigma': Rplus, 'nu': Rplus}, ref_rand=ref_rand)

    def test_vonmises(self):
        def ref_rand(size, mu, kappa):
            return st.vonmises.rvs(size=size, loc=mu, kappa=kappa)
        pymc3_random(pm.VonMises, {'mu': R, 'kappa': Rplus}, ref_rand=ref_rand)

    def test_flat(self):
        with pm.Model():
            f = pm.Flat('f')
            with pytest.raises(ValueError):
                f.random(1)

    def test_half_flat(self):
        with pm.Model():
            f = pm.HalfFlat('f')
            with pytest.raises(ValueError):
                f.random(1)

    def test_binomial(self):
        pymc3_random_discrete(pm.Binomial, {'n': Nat, 'p': Unit}, ref_rand=st.binom.rvs)

    def test_beta_binomial(self):
        pymc3_random_discrete(pm.BetaBinomial, {'n': Nat, 'alpha': Rplus, 'beta': Rplus},
                              ref_rand=self._beta_bin)

    def _beta_bin(self, n, alpha, beta, size=None):
        return st.binom.rvs(n, st.beta.rvs(a=alpha, b=beta, size=size))

    def test_bernoulli(self):
        pymc3_random_discrete(pm.Bernoulli, {'p': Unit},
                              ref_rand=lambda size, p=None: st.bernoulli.rvs(p, size=size))

    def test_poisson(self):
        pymc3_random_discrete(pm.Poisson, {'mu': Rplusbig}, size=500, ref_rand=st.poisson.rvs)

    def test_negative_binomial(self):
        def ref_rand(size, alpha, mu):
            return st.nbinom.rvs(alpha, alpha / (mu + alpha), size=size)
        pymc3_random_discrete(pm.NegativeBinomial, {'mu': Rplusbig, 'alpha': Rplusbig},
                              size=100, fails=50, ref_rand=ref_rand)

    def test_geometric(self):
        pymc3_random_discrete(pm.Geometric, {'p': Unit}, size=500, fails=50, ref_rand=nr.geometric)

    def test_discrete_uniform(self):
        def ref_rand(size, lower, upper):
            return st.randint.rvs(lower, upper + 1, size=size)
        pymc3_random_discrete(pm.DiscreteUniform, {'lower': -NatSmall, 'upper': NatSmall},
                              ref_rand=ref_rand)

    def test_discrete_weibull(self):
        def ref_rand(size, q, beta):
            u = np.random.uniform(size=size)

            return np.ceil(np.power(np.log(1 - u) / np.log(q), 1. / beta)) - 1

        pymc3_random_discrete(pm.DiscreteWeibull, {'q': Unit, 'beta': Rplusdunif},
                              ref_rand=ref_rand)

    @pytest.mark.parametrize('s', [2, 3, 4])
    def test_categorical_random(self, s):
        def ref_rand(size, p):
            return nr.choice(np.arange(p.shape[0]), p=p, size=size)
        pymc3_random_discrete(pm.Categorical, {'p': Simplex(s)}, ref_rand=ref_rand)

    def test_constant_dist(self):
        def ref_rand(size, c):
            return c * np.ones(size, dtype=int)
        pymc3_random_discrete(pm.Constant, {'c': I}, ref_rand=ref_rand)

    def test_mv_normal(self):
        def ref_rand(size, mu, cov):
            return st.multivariate_normal.rvs(mean=mu, cov=cov, size=size)

        def ref_rand_tau(size, mu, tau):
            return ref_rand(size, mu, linalg.inv(tau))

        def ref_rand_chol(size, mu, chol):
            return ref_rand(size, mu, np.dot(chol, chol.T))

        def ref_rand_uchol(size, mu, chol):
            return ref_rand(size, mu, np.dot(chol.T, chol))

        for n in [2, 3]:
            pymc3_random(pm.MvNormal, {'mu': Vector(R, n), 'cov': PdMatrix(n)},
                         size=100, valuedomain=Vector(R, n), ref_rand=ref_rand)
            pymc3_random(pm.MvNormal, {'mu': Vector(R, n), 'tau': PdMatrix(n)},
                         size=100, valuedomain=Vector(R, n), ref_rand=ref_rand_tau)
            pymc3_random(pm.MvNormal, {'mu': Vector(R, n), 'chol': PdMatrixChol(n)},
                         size=100, valuedomain=Vector(R, n), ref_rand=ref_rand_chol)
            pymc3_random(
                pm.MvNormal,
                {'mu': Vector(R, n), 'chol': PdMatrixCholUpper(n)},
                size=100, valuedomain=Vector(R, n), ref_rand=ref_rand_uchol,
                extra_args={'lower': False}
            )

    def test_matrix_normal(self):
        def ref_rand(size, mu, rowcov, colcov):
            return st.matrix_normal.rvs(mean=mu, rowcov=rowcov, colcov=colcov, size=size)

        # def ref_rand_tau(size, mu, tau):
        #     return ref_rand(size, mu, linalg.inv(tau))

        def ref_rand_chol(size, mu, rowchol, colchol):
            return ref_rand(size, mu, rowcov=np.dot(rowchol, rowchol.T),
                            colcov=np.dot(colchol, colchol.T))

        def ref_rand_uchol(size, mu, rowchol, colchol):
            return ref_rand(size, mu, rowcov=np.dot(rowchol.T, rowchol),
                            colcov=np.dot(colchol.T, colchol))

        for n in [2, 3]:
            pymc3_random(pm.MatrixNormal, {'mu': RealMatrix(n, n), 'rowcov': PdMatrix(n), 'colcov': PdMatrix(n)},
                         size=n, valuedomain=RealMatrix(n, n), ref_rand=ref_rand)
            # pymc3_random(pm.MatrixNormal, {'mu': RealMatrix(n, n), 'tau': PdMatrix(n)},
            #              size=n, valuedomain=RealMatrix(n, n), ref_rand=ref_rand_tau)
            pymc3_random(pm.MatrixNormal, {'mu': RealMatrix(n, n), 'rowchol': PdMatrixChol(n), 'colchol': PdMatrixChol(n)},
                         size=n, valuedomain=RealMatrix(n, n), ref_rand=ref_rand_chol)
            # pymc3_random(
            #     pm.MvNormal,
            #     {'mu': RealMatrix(n, n), 'rowchol': PdMatrixCholUpper(n), 'colchol': PdMatrixCholUpper(n)},
            #     size=n, valuedomain=RealMatrix(n, n), ref_rand=ref_rand_uchol,
            #     extra_args={'lower': False}
            # )

    def test_kronecker_normal(self):
        def ref_rand(size, mu, covs, sigma):
            cov = pm.math.kronecker(covs[0], covs[1]).eval()
            cov += sigma**2 * np.identity(cov.shape[0])
            return st.multivariate_normal.rvs(mean=mu, cov=cov, size=size)

        def ref_rand_chol(size, mu, chols, sigma):
            covs = [np.dot(chol, chol.T) for chol in chols]
            return ref_rand(size, mu, covs, sigma)

        def ref_rand_evd(size, mu, evds, sigma):
            covs = []
            for eigs, Q in evds:
                covs.append(np.dot(Q, np.dot(np.diag(eigs), Q.T)))
            return ref_rand(size, mu, covs, sigma)

        sizes = [2, 3]
        sigmas = [0, 1]
        for n, sigma in zip(sizes, sigmas):
            N = n**2
            covs = [RandomPdMatrix(n), RandomPdMatrix(n)]
            chols = list(map(np.linalg.cholesky, covs))
            evds = list(map(np.linalg.eigh, covs))
            dom = Domain([np.random.randn(N)*0.1], edges=(None, None), shape=N)
            mu = Domain([np.random.randn(N)*0.1], edges=(None, None), shape=N)

            std_args = {'mu': mu}
            cov_args = {'covs': covs}
            chol_args = {'chols': chols}
            evd_args = {'evds': evds}
            if sigma is not None and sigma != 0:
                std_args['sigma'] = Domain([sigma], edges=(None, None))
            else:
                for args in [cov_args, chol_args, evd_args]:
                    args['sigma'] = sigma

            pymc3_random(
                 pm.KroneckerNormal, std_args, valuedomain=dom,
                 ref_rand=ref_rand, extra_args=cov_args, model_args=cov_args)
            pymc3_random(
                 pm.KroneckerNormal, std_args, valuedomain=dom,
                 ref_rand=ref_rand_chol, extra_args=chol_args,
                 model_args=chol_args)
            pymc3_random(
                 pm.KroneckerNormal, std_args, valuedomain=dom,
                 ref_rand=ref_rand_evd, extra_args=evd_args,
                 model_args=evd_args)

    def test_mv_t(self):
        def ref_rand(size, nu, Sigma, mu):
            normal = st.multivariate_normal.rvs(cov=Sigma, size=size).T
            chi2 = st.chi2.rvs(df=nu, size=size)
            return mu + np.sqrt(nu) * (normal / chi2).T
        for n in [2, 3]:
            pymc3_random(pm.MvStudentT,
                         {'nu': Domain([5, 10, 25, 50]), 'Sigma': PdMatrix(
                             n), 'mu': Vector(R, n)},
                         size=100, valuedomain=Vector(R, n), ref_rand=ref_rand)

    def test_dirichlet(self):
        def ref_rand(size, a):
            return st.dirichlet.rvs(a, size=size)
        for n in [2, 3]:
            pymc3_random(pm.Dirichlet, {'a': Vector(Rplus, n)},
                         valuedomain=Simplex(n), size=100, ref_rand=ref_rand)

    def test_multinomial(self):
        def ref_rand(size, p, n):
            return nr.multinomial(pvals=p, n=n, size=size)
        for n in [2, 3]:
            pymc3_random_discrete(pm.Multinomial, {'p': Simplex(n), 'n': Nat},
                                  valuedomain=Vector(Nat, n), size=100, ref_rand=ref_rand)

    def test_gumbel(self):
        def ref_rand(size, mu, beta):
            return st.gumbel_r.rvs(loc=mu, scale=beta, size=size)
        pymc3_random(pm.Gumbel, {'mu': R, 'beta': Rplus}, ref_rand=ref_rand)

    def test_logistic(self):
        def ref_rand(size, mu, s):
            return st.logistic.rvs(loc=mu, scale=s, size=size)
        pymc3_random(pm.Logistic, {'mu': R, 's': Rplus}, ref_rand=ref_rand)

    def test_logitnormal(self):
        def ref_rand(size, mu, sd):
            return expit(st.norm.rvs(loc=mu, scale=sd, size=size))
        pymc3_random(pm.LogitNormal, {'mu': R, 'sd': Rplus}, ref_rand=ref_rand)

    @pytest.mark.xfail(condition=(theano.config.floatX == "float32"), reason="Fails on float32")
    def test_interpolated(self):
        for mu in R.vals:
            for sd in Rplus.vals:
                #pylint: disable=cell-var-from-loop
                def ref_rand(size):
                    return st.norm.rvs(loc=mu, scale=sd, size=size)

                class TestedInterpolated (pm.Interpolated):

                    def __init__(self, **kwargs):
                        x_points = np.linspace(mu - 5 * sd, mu + 5 * sd, 100)
                        pdf_points = st.norm.pdf(x_points, loc=mu, scale=sd)
                        super(TestedInterpolated, self).__init__(
                            x_points=x_points,
                            pdf_points=pdf_points,
                            **kwargs
                        )

                pymc3_random(TestedInterpolated, {}, ref_rand=ref_rand)

    @pytest.mark.skip('Wishart random sampling not implemented.\n'
                      'See https://github.com/pymc-devs/pymc3/issues/538')
    def test_wishart(self):
        # Wishart non current recommended for use:
        # https://github.com/pymc-devs/pymc3/issues/538
        # for n in [2, 3]:
        #     pymc3_random_discrete(Wisvaluedomainhart,
        #                           {'n': Domain([2, 3, 4, 2000]) , 'V': PdMatrix(n) },
        #                           valuedomain=PdMatrix(n),
        #                           ref_rand=lambda n=None, V=None, size=None: \
        #                           st.wishart(V, df=n, size=size))
        pass

    def test_lkj(self):
        for n in [2, 10, 50]:
            #pylint: disable=cell-var-from-loop
            shape = n*(n-1)//2

            def ref_rand(size, eta):
                beta = eta - 1 + n/2
                return (st.beta.rvs(size=(size, shape), a=beta, b=beta)-.5)*2

            class TestedLKJCorr (pm.LKJCorr):

                def __init__(self, **kwargs):
                    kwargs.pop('shape', None)
                    super(TestedLKJCorr, self).__init__(
                            n=n,
                            **kwargs
                    )

            pymc3_random(TestedLKJCorr,
                     {'eta': Domain([1., 10., 100.])},
                     size=10000//n,
                     ref_rand=ref_rand)

    def test_normalmixture(self):
        def ref_rand(size, w, mu, sd):
            component = np.random.choice(w.size, size=size, p=w)
            return np.random.normal(mu[component], sd[component], size=size)

        pymc3_random(pm.NormalMixture, {'w': Simplex(2),
                     'mu': Domain([[.05, 2.5], [-5., 1.]], edges=(None, None)),
                     'sd': Domain([[1, 1], [1.5, 2.]], edges=(None, None))},
                     extra_args={'comp_shape': 2},
                     size=1000,
                     ref_rand=ref_rand)
        pymc3_random(pm.NormalMixture, {'w': Simplex(3),
                     'mu': Domain([[-5., 1., 2.5]], edges=(None, None)),
                     'sd': Domain([[1.5, 2., 3.]], edges=(None, None))},
                     extra_args={'comp_shape': 3},
                     size=1000,
                     ref_rand=ref_rand)


def test_mixture_random_shape():
    # test the shape broadcasting in mixture random
    y = np.concatenate([nr.poisson(5, size=10),
                        nr.poisson(9, size=10)])
    with pm.Model() as m:
        comp0 = pm.Poisson.dist(mu=np.ones(2))
        w0 = pm.Dirichlet('w0', a=np.ones(2))
        like0 = pm.Mixture('like0',
                           w=w0,
                           comp_dists=comp0,
                           observed=y)

        comp1 = pm.Poisson.dist(mu=np.ones((20, 2)),
                                shape=(20, 2))
        w1 = pm.Dirichlet('w1', a=np.ones(2))
        like1 = pm.Mixture('like1',
                           w=w1,
                           comp_dists=comp1,
                           observed=y)

        comp2 = pm.Poisson.dist(mu=np.ones(2))
        w2 = pm.Dirichlet('w2',
                          a=np.ones(2),
                          shape=(20, 2))
        like2 = pm.Mixture('like2',
                           w=w2,
                           comp_dists=comp2,
                           observed=y)

        comp3 = pm.Poisson.dist(mu=np.ones(2),
                                shape=(20, 2))
        w3 = pm.Dirichlet('w3',
                          a=np.ones(2),
                          shape=(20, 2))
        like3 = pm.Mixture('like3',
                           w=w3,
                           comp_dists=comp3,
                           observed=y)

    rand0, rand1, rand2, rand3 = draw_values([like0, like1, like2, like3],
                                             point=m.test_point,
                                             size=100)
    assert rand0.shape == (100, 20)
    assert rand1.shape == (100, 20)
    assert rand2.shape == (100, 20)
    assert rand3.shape == (100, 20)

    with m:
        ppc = pm.sample_posterior_predictive([m.test_point], samples=200)
    assert ppc['like0'].shape == (200, 20)
    assert ppc['like1'].shape == (200, 20)
    assert ppc['like2'].shape == (200, 20)
    assert ppc['like3'].shape == (200, 20)


def test_density_dist_with_random_sampleable():
    with pm.Model() as model:
        mu = pm.Normal('mu', 0, 1)
        normal_dist = pm.Normal.dist(mu, 1)
        pm.DensityDist('density_dist', normal_dist.logp, observed=np.random.randn(100), random=normal_dist.random)
        trace = pm.sample(100)

    samples = 500
    ppc = pm.sample_posterior_predictive(trace, samples=samples, model=model, size=100)
    assert len(ppc['density_dist']) == samples


def test_density_dist_without_random_not_sampleable():
    with pm.Model() as model:
        mu = pm.Normal('mu', 0, 1)
        normal_dist = pm.Normal.dist(mu, 1)
        pm.DensityDist('density_dist', normal_dist.logp, observed=np.random.randn(100))
        trace = pm.sample(100)

    samples = 500
    with pytest.raises(ValueError):
        pm.sample_posterior_predictive(trace, samples=samples, model=model, size=100)
